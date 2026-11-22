# Installation

> **Draft.** An installer is on the way. Until then these are the manual steps. They have not been tried on a
> fresh Deck yet: please open an issue if a step fails.

Everything goes into one folder, `~/wowvoice`. Nothing is installed system-wide and no root password is needed.

## 1. Get the files

Switch to **Desktop Mode** and open **Konsole**.

```bash
git clone https://github.com/yerenutku/my-steam-deck-gets-me.git ~/wowvoice
cd ~/wowvoice
```

## 2. Python and packages

```bash
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/wowvoice/tools/bin" INSTALLER_NO_MODIFY_PATH=1 sh
source env.sh
uv venv --python 3.12 envs/sherpa
uv pip install --python envs/sherpa/bin/python -r envs/requirements-sherpa.txt
```

## 3. Speech model and pause detector (about 1.2 GB)

```bash
mkdir -p models/gguf/handy-computer--parakeet-unified-en-0.6b-gguf
curl -L -o models/gguf/handy-computer--parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-F16.gguf \
  https://huggingface.co/handy-computer/parakeet-unified-en-0.6b-gguf/resolve/main/parakeet-unified-en-0.6b-F16.gguf
curl -L -o models/silero_vad.onnx \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
```

## 4. The WoW addon

Copy `addon/WowVoice` into WoW's AddOns folder:

```bash
WOW=$(ls -d ~/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/"Program Files (x86)"/"World of Warcraft"/_forever_ | head -1)
cp -r addon/WowVoice "$WOW/Interface/AddOns/"
```

In WoW: **Options → Social → Chat Style: Classic**. (The "IM" style keeps the chat box focused after sending.)

## 5. Controller (one time, in Steam)

R4 must do nothing else in WoW, and the right stick must not turn the camera while the wheel is open.

1. Steam → your WoW / Battle.net entry → **Controller settings** → **Edit layout**.
2. **Back grip buttons:** remove any command from **R4**.
3. **Right joystick:** open its settings → **Mode shift** → button **R4** → mode **Directional Pad**, and leave its
   four directions **empty**. While R4 is held, the right stick then only steers the wheel.

## 6. Start it, and start it with the Deck

```bash
mkdir -p ~/.config/systemd/user
cp service/wowvoice.service ~/.config/systemd/user/
systemctl --user enable --now wowvoice
```

The tool now starts with the Deck, in Desktop and Game Mode, but sleeps until you start Battle.net or WoW: no
microphone, no speech model, no CPU until then. While you play, the microphone is only open while R4 is held.
In WoW you'll see **Voice ready** shortly after logging in.

## 7. Try it

Start WoW, hold **R4**, say "anyone want to run Deadmines", let go. After about a second the text appears in a
box under the chat and is sent after a 2-second countdown (**B** throws it away).

Add your friends' and guild's names to `service/names.txt` (one per line); the tool rereads it by itself.

## Troubleshooting

- Status and errors: `systemctl --user status wowvoice` and `~/wowvoice/.cache/service.log`.
- Restart: `systemctl --user restart wowvoice`. Never start a second copy by hand.

## Uninstall

```bash
systemctl --user disable --now wowvoice
rm ~/.config/systemd/user/wowvoice.service
rm -rf ~/wowvoice "$WOW/Interface/AddOns/WowVoice"
```
