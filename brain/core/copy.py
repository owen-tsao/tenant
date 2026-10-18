"""Human-readable room messages, derived from observed acknowledgments only."""


def device_label(dev):
    """Use the host's visible label, never an internal identifier or raw result."""
    label = getattr(dev, 'label', None)
    return ' '.join(label.split()) if isinstance(label, str) and label.strip() else 'The device'


def requested_sentence(actor, dev, cap, args):
    label = device_label(dev)
    args = args if isinstance(args, dict) else {}
    if cap == 'light' and type(args.get('on')) is bool:
        action = 'turn its flashlight ' + ('on' if args['on'] else 'off')
    elif cap == 'music.play':
        action = 'play music'
    elif cap == 'music.pause':
        action = 'pause music'
    elif cap == 'say':
        action = 'speak'
    elif cap == 'volume':
        action = 'change its volume'
    else:
        action = 'carry out a request'
    return f'{actor} asked {label} to {action}.'


def confirmed_sentence(dev, cap, args, result):
    """Describe a successful result payload without inferring physical audibility.

    A missing or unexpected result is a generic acknowledgment, never evidence
    that requested arguments became physical state. Speech text is not echoed.
    """
    label = device_label(dev)
    result = result if isinstance(result, dict) else {}
    if cap == 'light' and type(result.get('on')) is bool:
        return f'{label} turned its flashlight {"on" if result["on"] else "off"}.'
    if cap == 'music.play' and result.get('state') == 'playing':
        return f'{label} started playing music.'
    if cap == 'music.pause' and result.get('state') == 'paused':
        return f'{label} paused the music.'
    if cap == 'music.pause' and result.get('state') == 'stopped':
        return f'{label} confirmed the music is stopped.'
    if cap == 'say' and result.get('spoken') is True:
        return f'{label} reported that speech playback finished.'
    level = result.get('level')
    if cap == 'volume' and type(level) is int and 0 <= level <= 100:
        return f'{label} set its volume to {level} percent.'
    return f'{label} confirmed the request.'


def failure_sentence(dev, cap, args, result):
    """Describe failure without exposing device error strings or implying undo."""
    label = device_label(dev)
    code = getattr(result, 'code', None)
    if code == 'UNKNOWN':
        return f'The outcome for {label} is unknown. I did not retry or use another device.'
    if code == 'TIMEOUT':
        return 'The request expired while waiting; nothing was sent. I did not retry.'
    if code == 'OFFLINE':
        return f'{label} is unavailable. The action was not confirmed.'
    if code == 'PERMISSION':
        return f'Permission was denied for {label}. The action was not confirmed.'
    if code == 'BUSY':
        return f'{label} is busy. The action was not confirmed.'
    return f'{label} did not confirm the requested action.'


def supported_sentence(dev, caps):
    """Translate the supported core capabilities into ordinary room language."""
    actions = []
    if 'light' in caps:
        actions.append('turn its flashlight on or off')
    if 'music.play' in caps and 'music.pause' in caps:
        actions.append('play or pause music')
    elif 'music.play' in caps:
        actions.append('play music')
    elif 'music.pause' in caps:
        actions.append('pause music')
    if 'say' in caps:
        actions.append('speak')
    if 'volume' in caps:
        actions.append('change its volume')
    if not actions:
        return None
    listed = actions[0] if len(actions) == 1 else ', '.join(actions[:-1]) + ' and ' + actions[-1]
    return f'{device_label(dev)} can {listed}.'
