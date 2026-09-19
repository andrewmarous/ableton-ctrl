# ableton-ctrl

Read-only Ableton Live Set inspection through a local bridge.

## Install

```bash
uv tool install ableton-ctrl
ableton-ctrl install --with-pi --with-kb --kb-path "$HOME/Documents/Ableton Knowledge"
ableton-ctrl doctor
```

In Live, select **AbletonCtrl** in Preferences > Link, Tempo & MIDI > Control Surface.

Add local knowledge sources with:

```bash
ableton-ctrl kb add tutorial.md
ableton-ctrl kb lint
```

See [Getting started](docs/getting-started.md), [installation](docs/install.md), and [troubleshooting](docs/troubleshooting.md). Ableton's Python API is unsupported; the supported target is macOS with Ableton Live 12.4.2 Standard.
