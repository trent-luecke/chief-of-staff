# Mirror setup & refresh

The mirror lives at `~/dev/gymstudio/` — OUTSIDE the chief-of-staff repo. Never commit it.

Clone over **SSH** (`git@github.com:...`), not HTTPS. SSH uses the key that already
authenticates the chief-of-staff repo, so the pre-run refresh needs no credential
prompt or helper. (A plain `git pull` on an HTTPS remote fails with "could not read
Username for https://github.com" unless a git credential helper is wired up.)

## First-time clone (SSH)
    mkdir -p ~/dev/gymstudio && cd ~/dev/gymstudio
    git clone --depth 1 git@github.com:GymStudio/backend.git
    git clone --depth 1 git@github.com:GymStudio/admin-frontend.git

If a mirror was previously cloned over HTTPS, convert it in place (no re-clone needed):
    git -C ~/dev/gymstudio/backend remote set-url origin git@github.com:GymStudio/backend.git
    git -C ~/dev/gymstudio/admin-frontend remote set-url origin git@github.com:GymStudio/admin-frontend.git

## Refresh before every analysis run
    git -C ~/dev/gymstudio/backend pull --ff-only
    git -C ~/dev/gymstudio/admin-frontend pull --ff-only

## On-demand (member-facing entry points)
    cd ~/dev/gymstudio && git clone --depth 1 git@github.com:GymStudio/client-frontend.git

## Record the SHA in every report
    git -C ~/dev/gymstudio/backend rev-parse --short HEAD

If a mirror directory is missing, run the first-time clone and STOP — do not analyze against a missing mirror.
