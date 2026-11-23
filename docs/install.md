# Installation

Everything goes into one folder, `~/my-steam-deck-gets-me`. Nothing is installed system-wide and no root password is needed.
It takes about 10 minutes, mostly the 1.2 GB speech model download.

## 1. Run the installer

Switch to **Desktop Mode**, open **Konsole** and paste:

```bash
git clone https://github.com/yerenutku/my-steam-deck-gets-me.git ~/my-steam-deck-gets-me && bash ~/my-steam-deck-gets-me/install.sh
```

It sets up Python and its packages, downloads the speech model and the pause detector, copies the addon into WoW
and starts the tool with the Deck. It's safe to run again: it skips what is already there.

Install WoW Forever first (Battle.net as a non-Steam game), so the installer can find WoW's AddOns folder.

## 2. The camera lock (asked by the installer)

While you pick a chat destination on the wheel, the right stick would also turn your camera. That's solved with a
**mode shift** on the right stick that turns on while R4 is held. At the end, the installer offers three choices:

1. **Set it up for me.** You close Steam for a moment; the installer adds the mode shift to your Battle.net layout.
   If your right stick already had a mode shift on any button, it is replaced; everything else stays as it is. Your
   original is saved first; `bash ~/my-steam-deck-gets-me/restore-controller-layout.sh` puts it back (with Steam closed).
2. **Show me how**, to do it yourself in Steam:
   your WoW / Battle.net entry → **Controller settings** → **Edit layout** →
   - **Back grip buttons:** remove any command from **R4**.
   - **Right joystick:** its settings → **Mode shift** → button **R4** → mode **Directional Pad**, and leave its
     four directions **empty**.
3. **Skip**, and run the installer again later.

## 3. Try it

Start Battle.net and WoW. Shortly after you enter the world, **Voice ready** appears. Hold **R4**, say "anyone want
to run Deadmines", let go: the text appears in a box under the chat and is sent after a 2-second countdown
(**B** throws it away).

Names come from your game: friends, guild, group, quests, bags and vendors. The first time, the addon asks you
to reload once (double-press and hold R4, then Options > Refresh context); after that it keeps them fresh.

The tool sleeps until you start Battle.net or WoW: no microphone, no speech model, no CPU until then. While you play,
the microphone opens at your first press and closes after 2 minutes without use.

## Troubleshooting

- Status and errors: `systemctl --user status my-steam-deck-gets-me` and `~/my-steam-deck-gets-me/.cache/service.log`.
- Restart: `systemctl --user restart my-steam-deck-gets-me`. Never start a second copy by hand.
- "No contact with the tool" in WoW's chat: the tool isn't running; check the two lines above.

## Uninstall

```bash
bash ~/my-steam-deck-gets-me/uninstall.sh
```

It removes the autostart and the addon, and asks before deleting `~/my-steam-deck-gets-me`.
