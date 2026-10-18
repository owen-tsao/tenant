# Tenant customers and competitive advantage

For Jay and Owen, October 17, 2026. Use this as the shared customer, positioning and moat reference for the demo. Customer segments and defensibility below are hypotheses; the prototype evidence is identified separately.

**Positioning to test:** Tenant lets guests use a space’s connected capabilities through one conversation, with temporary access and verified results.

## What customers might pay for

Start by investigating professional short-term rental managers with dispersed properties, existing connected equipment and limited on-site staff. Their potential reason to buy is fewer equipment problems requiring a support call or visit. Hotels have a different staffing model and buying process and need a separate hypothesis.

| Candidate buyer | Paid outcome to investigate | Evidence that would justify a purchase |
| --- | --- | --- |
| Professional Airbnb or other short-term rental operator | Guests complete supported equipment requests; staff diagnose problems remotely and receive useful escalations. | Fewer avoidable visits and less total support time per occupied stay. |
| Independent hotel owner or operations lead | Routine room requests reach the right permitted equipment or staff member, with an accurate outcome. | Less front-desk handling time without increasing unresolved requests or complaints. |
| Venue, shared-space or event operator | Visitors use an unfamiliar space without repeated staff setup; presenters can coordinate supported equipment conversationally. | Less setup/support time and repeat use across events. |
| Hospitals and other environments Jay mentioned | Possible later applications for accessible interaction and room coordination. | A specific buyer and workflow first; no hospital integration or clinical claim is part of this demo. |

A concrete precedent: Berlin Apartments’ founder describes using Minut temperature information to diagnose a heating complaint remotely and avoid sending someone to the property. This vendor-hosted account supports the value of physical state and remote diagnosis; it does not establish Tenant demand or quantified savings. [Minut operator case](https://www.minut.com/case-studies/berlin-apartments).

Minut already publishes monitoring subscriptions and optional call assistance, so operators have existing offers to compare against. Those advertised prices are neither actual Tenant willingness to pay nor a reason to copy its pricing. [Minut pricing](https://www.minut.com/pricing).

Judge value using avoided visits, labor genuinely saved and avoided refunds, minus Tenant’s installation, maintenance, support, hardware and inference costs. Count time spent fixing Tenant. A paid pilot and renewal would be stronger evidence than interest in the demo; Tenant pricing is undecided.

## Why operators might choose Tenant

Investigate the complete guest lifecycle: arrive, receive permitted capabilities, request an outcome, execute and check it, handle failure, then end access. A useful distinction would be completing a supported physical request across the operator’s existing systems while keeping guest authority temporary and the outcome visible.

Existing products already cover substantial parts of this:

- **Hospitable** exposes property, messaging and device tools through MCP, including device status and smart-lock actions. Its documentation currently limits agent connections to primary account holders and full-access administrators. That makes guest-specific delegation worth investigating, without establishing an exclusive gap. [Hospitable documentation](https://help.hospitable.com/en/articles/14424057-connect-an-ai-agent-to-hospitable-using-mcp).
- **Google Home** documents device discovery, live state, actions and history through its Early Access MCP server. **Home Assistant** also exposes device control to AI through MCP. Connectivity alone is a weak competitive claim. [Google documentation](https://developers.home.google.com/mcp/home), [Home Assistant documentation](https://www.home-assistant.io/integrations/mcp_server).
- **Operto** already markets hospitality guest controls and integrations, including lighting, music and thermostats. Tenant must show an incremental operational benefit over an existing room-control product. [Operto Guest](https://operto.com/guest/).

Reuse working integrations. The candidate product advantage is a consistent relationship between guest identity, current permissions, available capabilities, execution and observed results. An acknowledgment means a command was acknowledged; physical completion requires the appropriate device or observation evidence. When the result is unknown, report that uncertainty. When an alternative device is available, offer it and wait for the guest’s choice.

## Building ahead of the curve

Jay’s thesis is that stronger reasoning, multimodal perception and coordination will make physical spaces increasingly useful to AI. Tenant can prepare a room’s capabilities, authority boundaries and execution feedback so better agents can use that groundwork. Agent interchangeability, broad multimodal support, large-scale deployment and offline operation remain design goals.

Better AI also helps competitors. A moat would have to accumulate through something harder to reproduce:

| Potential advantage | What would demonstrate it |
| --- | --- |
| Reusable knowledge of devices, capabilities, ownership and permissions | A new supported setup or agent needs less configuration without losing authority boundaries. |
| Reliable coordination and recovery across providers | Reproducible completion, honest failure and cancellation under disconnects, delayed acknowledgments and revocation. |
| Deployment experience and permitted outcome records | Later installations require less staff time and suffer fewer repeated failures. |
| Adoption and distribution | Outside builders connect spaces, contribute connectors or bring Tenant into repeat deployments. |

Before customers, build evidence with the equipment already available: reuse one capability/permission/result contract; compare supported requests across changed device setups; publish a small reproducible failure benchmark; and let an outside developer run one reference example without a guided setup. These are queued ways to establish technical lead and developer adoption, not additional hackathon features. They do not establish willingness to pay.

Proactivity should serve a concrete purpose: notice a supported device is unavailable, explain the limitation and offer an available alternative. Deterministic code should enforce permissions, scheduling and cancellation; AI should interpret intent and plan within those constraints. Autonomous observation and adaptation need their own demonstration before becoming a present-tense product claim.

## What the current demo can substantiate

At integrated revision `e4b8426`, the latest actual guest-UI run created, opened and conversationally revised a real Mac document. Jay also heard the selected Daniel Caesar recording and observed phone pulses aligning with it in one smoke test. That establishes a narrow working example, not measured synchronization accuracy or reliability. The independent light-stop/music-continues sequence was interrupted and remains unaccepted; final physical cleanup was confirmed. [Latest live evidence](../tests/evidence/2026-10-17-local-e2e-batch4.json).

Photo capture still needs Owen’s actual consent/capture/viewer UI before physical acceptance. Projector output, production hospitality operation, general autonomous adaptation and arbitrary device compatibility are future claims. Use verified capabilities for the main sequence and keep creative coordination optional until its remaining acceptance is complete.

## Points for Owen to add to the demo

1. **Today:** “Scan into a space and give its agent a natural request. Tenant can use the connected computer and supported devices through the same conversation.” Show the working behavior rather than promising every app or device.
2. **Customer hypothesis:** “For a rental or hotel operator, the value could be fewer room problems needing staff intervention, with a clear record of what actually happened.” Present hospitality as an initial market to validate.
3. **Future advantage:** “As AI gets better at seeing, reasoning and coordinating, Tenant aims to give it a reusable way to act in physical spaces—with permissions and feedback already built in.” Pair this with the longer-term moat candidates above, not a guaranteed future-proofing claim.

Owen: please add your strongest customer problem, competitive objection and explanation of why this live experience matters to the pitch or demo notes. Link any new factual claims to evidence and put unvalidated ideas here as hypotheses. Record the resulting deck/demo revision in `notes/owen.md`; Jay’s agent will not edit `web/` or the slides.

## Customer validation after the hackathon

Speak with three to five operators and review a recent month of anonymized support incidents, dispatch costs, staff time and current software bills. Separate questions that existing guides can answer from supported physical actions and jobs requiring a person. Choose one recurring costly workflow, compare Tenant against the operator’s current solution, and offer a narrow paid pilot with an agreed success measure. Expand only if the net operational benefit justifies doing so.

Keep experience candidates and creative demos in [demo ideas](demo-ideas.md). Keep implementation status and coordination in [Jay’s log](jay.md) and [Owen’s log](owen.md). This strategy adds no device, integration or feature to the current build.
