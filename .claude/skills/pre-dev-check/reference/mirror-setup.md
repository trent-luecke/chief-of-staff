# Mirror setup & refresh

The mirror lives at `~/dev/gymstudio/` — OUTSIDE the chief-of-staff repo. Never commit it.

## First-time clone
    mkdir -p ~/dev/gymstudio && cd ~/dev/gymstudio
    gh repo clone GymStudio/backend -- --depth 1
    gh repo clone GymStudio/admin-frontend -- --depth 1

## Refresh before every analysis run
    git -C ~/dev/gymstudio/backend pull --depth 1 --ff-only
    git -C ~/dev/gymstudio/admin-frontend pull --depth 1 --ff-only

## On-demand (member-facing entry points)
    cd ~/dev/gymstudio && gh repo clone GymStudio/client-frontend -- --depth 1

## Record the SHA in every report
    git -C ~/dev/gymstudio/backend rev-parse --short HEAD

If a mirror directory is missing, run the first-time clone and STOP — do not analyze against a missing mirror.
