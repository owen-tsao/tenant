"""One validated action per guest turn. Planning never holds physical authority."""
import asyncio
import copy
import re
from collections import defaultdict
from brain.core.tools import inventory_for, valid_action, alternatives_for
from brain.core.copy import (confirmed_sentence, device_label, failure_sentence,
                             requested_sentence, supported_sentence)


class Agent:
    def __init__(self, registry, bus, leases, planner, log, *, action_timeout=5.0):
        self.registry, self.bus, self.leases = registry, bus, leases
        self.planner, self.log = planner, log
        self.action_timeout = action_timeout
        self.locks = defaultdict(asyncio.Lock)
        self.pending = {}

    @staticmethod
    def reply(text, action=None):
        frames = []
        if action:
            frames.append({'type': 'action', 'text': action})
        frames.append({'type': 'assistant', 'text': text})
        return frames

    def denied(self, guest_id):
        self.pending.pop(guest_id, None)
        self.log.append('denied', 'Guest access has ended. Further control was denied.', guest_id=guest_id)
        return self.reply(self.leases.denial(guest_id))

    async def turn(self, guest_id, text):
        async with self.locks[guest_id]:
            lease = self.leases.current(guest_id, activate=True)
            if not lease:
                return self.denied(guest_id)
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                return self.reply('Please send a request of 1–2000 characters.')
            text = text.strip()
            session = self.leases.sessions[guest_id]
            session.last_active = self.leases.clock()
            if self.normalize(text) in ('leave', 'goodbye', 'done'):
                return await self.execute_plan(lease, {'kind': 'leave'})
            # Explicit choice is resolved locally; the model cannot silently choose a fallback.
            if guest_id in self.pending:
                return await self.choose(lease, text)
            session.messages.append({'role': 'user', 'content': text})
            del session.messages[:-20]
            if self.planner is None:
                return self.reply('Room planning is unavailable. Ask the host to connect it.')
            try:
                async with asyncio.timeout(15):
                    plan = await self.planner.plan(text, inventory_for(self.registry, self.leases, lease),
                                                   copy.deepcopy(session.messages))
            except (Exception, TimeoutError):
                self.log.append('err', 'Room planning is unavailable. No command was sent.', guest_id=guest_id)
                return self.reply("The room's thinking is unavailable. Please try again.")
            if not self.leases.current(guest_id):
                return self.denied(guest_id)
            frames = await self.execute_plan(lease, plan, user_text=text)
            session.messages.append({'role': 'assistant', 'content': frames[-1]['text']})
            del session.messages[:-20]
            return frames

    def named_devices(self, text):
        """Match known labels/IDs only; longest aliases win overlapping matches."""
        normalized = self.normalize(text)
        matches = []
        for dev in self.registry.devices.values():
            if dev.room_id != self.registry.room.id:
                continue
            for alias in {self.normalize(dev.id), self.normalize(dev.label)}:
                if not alias:
                    continue
                for match in re.finditer(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', normalized):
                    matches.append((len(alias), match.start(), match.end(), dev.id))
        selected, spans = set(), []
        for _, start, end, device_id in sorted(matches, reverse=True):
            if any(start < right and end > left and (start, end) != (left, right) for left, right in spans):
                continue
            selected.add(device_id)
            spans.append((start, end))
        return selected

    def help_text(self, lease):
        devices = [d for d in self.registry.devices.values() if d.room_id == self.registry.room.id and d.online]
        descriptions = []
        for dev in devices:
            caps = [cap for cap in dev.caps if self.registry.metadata.available(dev, cap)
                    and ('*' in lease.scopes or cap in lease.scopes)]
            sentence = supported_sentence(dev, caps)
            if sentence:
                descriptions.append(sentence)
        if not descriptions:
            return 'No permitted devices are connected. No device action was taken.'
        return ' '.join(descriptions) + ' No device action was taken.'

    def label_is_ambiguous(self, dev):
        label = self.normalize(dev.label)
        return sum(self.normalize(other.label) == label for other in self.registry.devices.values()
                   if other.room_id == self.registry.room.id) > 1

    @staticmethod
    def rename_reply():
        return 'Some devices share the same name. Ask the host to give them different names, then choose again. No command was sent.'

    async def execute_plan(self, lease, plan, *, user_text=''):
        if not isinstance(plan, dict):
            return self.reply('That request could not be safely understood. Please rephrase it.')
        kind = plan.get('kind')
        if kind == 'leave' and set(plan) <= {'kind', 'text'}:
            self.leases.revoke(lease.guest_id)
            self.pending.pop(lease.guest_id, None)
            self.log.append('guest.leave', f'{lease.display_name} ended access. Existing effects stay as set.',
                            guest_id=lease.guest_id)
            return self.reply('Your room access has ended. Existing effects stay as set.')
        if kind == 'message' and set(plan) <= {'kind', 'text'}:
            text = plan.get('text')
            if isinstance(text, str) and 0 < len(text) <= 500:
                return self.reply(self.help_text(lease))
        if kind in ('action', 'suggest'):
            allowed = {'kind', 'device_id', 'cap', 'args'} | ({'alternatives', 'text'} if kind == 'suggest' else set())
            if not set(plan) <= allowed:
                return self.reply('That action is unsupported. No command was sent.')
            if not isinstance(plan.get('device_id'), str) or not isinstance(plan.get('cap'), str):
                return self.reply('That action is malformed. No command was sent.')
            named = self.named_devices(user_text)
            if len(named) > 1:
                if any(self.label_is_ambiguous(self.registry.devices[device_id]) for device_id in named):
                    return self.reply(self.rename_reply())
                return self.reply('Please name one device for this request. No command was sent.')
            if named and plan.get('device_id') not in named:
                requested = self.registry.devices[next(iter(named))]
                if requested.online:
                    return self.reply(f'You named {device_label(requested)}. Please confirm that device. No command was sent.')
                plan = dict(plan, device_id=requested.id)
            dev = valid_action(self.registry, lease, plan)
            if dev:
                if self.label_is_ambiguous(dev):
                    return self.reply(self.rename_reply())
                if not dev.online:
                    return self.suggest(lease, plan)
                if kind == 'suggest':
                    return self.reply(f'{device_label(dev)} is connected. Please name the device you want. No command was sent.')
                return await self.dispatch(lease, plan)
        self.log.append('denied', 'The request was unsupported or not permitted. No command was sent.', guest_id=lease.guest_id)
        return self.reply('That action is unsupported or not permitted. No command was sent.')

    def suggest(self, lease, plan):
        if not self.leases.current(lease.guest_id):
            return self.denied(lease.guest_id)
        source = self.registry.devices[plan['device_id']]
        options = alternatives_for(self.registry, lease, source.id, plan['cap'], plan['args'])
        # Ignore untrusted alternative IDs; derive suitability from current schemas and permissions.
        if not options:
            return self.reply(f'{device_label(source)} is unavailable. No suitable alternative is connected.')
        if any(self.label_is_ambiguous(dev) for dev in options):
            self.pending.pop(lease.guest_id, None)
            return self.reply(self.rename_reply())
        self.pending[lease.guest_id] = {'device_id': source.id, 'cap': plan['cap'],
                                        'args': copy.deepcopy(plan['args']), 'options': [d.id for d in options]}
        labels = ', '.join(device_label(dev) for dev in options)
        return self.reply(f'{device_label(source)} is unavailable. Available alternatives: {labels}. Which should I use?')

    @staticmethod
    def normalize(text):
        return ' '.join(re.sub(r'[^\w\s]', '', text.casefold()).split())

    async def choose(self, lease, text):
        pending = self.pending[lease.guest_id]
        normalized = self.normalize(text)
        if normalized in ('no', 'cancel', 'never mind', 'nevermind'):
            self.pending.pop(lease.guest_id, None)
            return self.reply('Cancelled. No alternative was used.')
        if normalized in ('leave', 'goodbye', 'done'):
            return await self.execute_plan(lease, {'kind': 'leave'})
        choices = []
        for device_id in pending['options']:
            dev = self.registry.devices.get(device_id)
            if not dev:
                continue
            names = {self.normalize(dev.label)}
            if normalized in names or normalized in {'use ' + n for n in names}:
                choices.append(dev)
        if normalized in ('yes', 'use it', 'okay', 'ok') and len(pending['options']) == 1:
            candidate = self.registry.devices.get(pending['options'][0])
            choices = [candidate] if candidate else []
        if len(choices) != 1:
            return self.reply('Please choose a listed device by name, or say cancel. No command was sent.')
        choice = choices[0]
        if self.label_is_ambiguous(choice):
            self.pending.pop(lease.guest_id, None)
            return self.reply(self.rename_reply())
        plan = {'kind': 'action', 'device_id': choice.id, 'cap': pending['cap'], 'args': pending['args']}
        self.pending.pop(lease.guest_id, None)
        if not valid_action(self.registry, lease, plan):
            return self.reply('That alternative is no longer permitted or supported. No command was sent.')
        if not choice.online:
            return self.suggest(lease, plan)
        return await self.dispatch(lease, plan)

    async def dispatch(self, lease, plan):
        device_id, cap = plan['device_id'], plan['cap']
        dev = self.registry.devices.get(device_id)
        self.log.append('cmd', requested_sentence(lease.display_name, dev, cap, plan['args']),
                        guest_id=lease.guest_id, device_id=device_id, cap=cap)
        result = await self.bus.call(device_id, cap, plan['args'], timeout=self.action_timeout,
                                     authorize=lambda dev, capability, args: self.leases.allows(lease, dev, capability))
        req = getattr(result, 'req', None)
        sentence = (confirmed_sentence(dev, cap, plan['args'], result.result) if result.ok
                    else failure_sentence(dev, cap, plan['args'], result))
        self.log.append('ok' if result.ok else 'err', sentence, guest_id=lease.guest_id,
                        device_id=device_id, cap=cap, req=req, ok=result.ok, code=result.code)
        if result.ok:
            # Do not claim an in-flight action was cancelled by later revocation.
            return self.reply(sentence, sentence)
        if result.code == 'PERMISSION':
            if not self.leases.current(lease.guest_id):
                return self.denied(lease.guest_id)
            return self.reply(sentence)
        if result.code == 'OFFLINE':
            return self.suggest(lease, plan)
        return self.reply(sentence)
