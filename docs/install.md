# Installation

Everything goes into one folder, `~/wowvoice`. Nothing is installed system-wide and no root password is needed.
It takes about 10 minutes, mostly the 1.2 GB speech model download.

## 1. Run the installer

Switch to **Desktop Mode**, open **Konsole** and paste:

```bash
git clone https://github.com/yerenutku/my-steam-deck-gets-me.git ~/wowvoice && bash ~/wowvoice/install.sh
```

It sets up Python and its packages, downloads the speech model and the pause detector, copies the addon into WoW
and starts the tool with the Deck. It's safe to run again: it skips what is already there.

Install WoW Forever first (Battle.net as a non-Steam game), so the installer can find WoW's AddOns folder.

## 2. Two settings, one time only

**In WoW:** Options → Social → **Chat Style: Classic**. (The "IM" style keeps the chat box focused after sending.)

**In Steam**, so the right stick doesn't turn the camera while the wheel is open:

1. Steam → your WoW / Battle.net entry → **Controller settings** → **Edit layout**.
2. **Back grip buttons:** remove any command from **R4**.
3. **Right joystick:** open its settings → **Mode shift** → button **R4** → mode **Directional Pad**, and leave its
   four directions **empty**.

## 3. Try it

Start Battle.net and WoW. Shortly after you enter the world, **Voice ready** appears. Hold **R4**, say "anyone want
to run Deadmines", let go: the text appears in a box under the chat and is sent after a 2-second countdown
(**B** throws it away).

Add your friends' and guild's names to `~/wowvoice/service/names.txt` (one per line); the tool rereads it by itself.

The tool sleeps until you start Battle.net or WoW: no microphone, no speech model, no CPU until then. While you play,
the microphone opens at your first press and closes after 2 minutes without use.

## Troubleshooting

- Status and errors: `systemctl --user status wowvoice` and `~/wowvoice/.cache/service.log`.
- Restart: `systemctl --user restart wowvoice`. Never start a second copy by hand.
- "No contact with the tool" in WoW's chat: the tool isn't running; check the two lines above.

## Uninstall

```bash
bash ~/wowvoice/uninstall.sh
```

It removes the autostart and the addon, and asks before deleting `~/wowvoice`.
