"""Explicit photo backend installation; lifecycle/device/native hooks stay with Core."""
from brain.api.photos import router
from brain.core.photos import PhotoService


def install_photos(app, core, *, authority=None, **options):
    """Install before StaticFiles. No file access, network, tasks or device dispatch.

    Native mode uses the exact existing controller/generation policy. Other
    integrations must explicitly provide an authority policy; absence denies.
    Root must also apply the synchronous reset/revoke/sweep and device hooks.
    """
    if getattr(core, 'photos', None) is not None:
        raise ValueError('Photo backend already installed')
    if authority is None:
        authority = getattr(core.agent, 'allows_program', lambda lease, generation: False)
    core.photos = PhotoService(core.registry, core.bus, core.leases, authority=authority, **options)
    metadata = getattr(core.registry, 'metadata', None)
    if metadata is not None:
        metadata.camera_ready = core.photos.camera_ready
    if getattr(core.agent, 'device_tools', None) is not None:
        core.agent.device_tools.photos = core.photos
    app.include_router(router)
    return core.photos
