-- Runs last: the hooks are installed only once every definition above is in place. A fragment that
-- fails to load therefore leaves the previous handlers active and H.source_hash unset, and
-- Game.ensure_runtime re-injects the whole runtime on the next call.
H.install_hooks()
