# My Steam Deck Gets Me

**Voice chat-typing for World of Warcraft on the Steam Deck.** Hold a back button, speak, let go: your words
appear in WoW's chat. Accurate, fast, and entirely on your Deck. Nothing is sent to the internet.

<!-- screenshot: the wheel in game -->

## Why

- **Accurate with WoW words.** Dungeons, zones, items, "LF2M", and your friends' names. A names step fixes what
  speech models usually get wrong.
- **Fast.** About 1 second from letting go to text in chat. The speech model runs on the Deck's GPU in about
  0.3 s, without a noticeable drop in frame rate.
- **Made for a controller.** Pick the chat channel or a friend with the right stick on an in-game wheel. Fix a
  misheard word with the D-pad. No keyboard needed.
- **Light.** It sleeps until you start Battle.net, and the microphone only opens while you hold the button.
- **Private.** Speech recognition runs locally. No account, no cloud. Your last 200 dictations are kept on
  the Deck only (for corrections and testing); you can delete them any time.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/accuracy-dark.png">
  <img alt="Word error rate of My Steam Deck Gets Me compared with other setups and tools" src="docs/charts/accuracy-light.png">
</picture>

We tested 6 speech models and 5 engines on real WoW chat. My Steam Deck Gets Me makes about a third fewer mistakes than
the next-best existing tool we tested, at the same or better speed. → **[Read the lab report](docs/lab-report.md)**

## How to use it

| Back button R4 | What happens |
|---|---|
| **Hold**, speak, let go | Text goes to your last channel; sent after a short countdown |
| **Double-press and hold** | The wheel opens: aim with the right stick at Say, Party, Guild, Whisper, Friends… then speak |
| **Double-press** | Correction menu: D-pad picks a word and its alternatives; hold R4 to say one word again |
| **A** / **B** | Send now / throw away |

Options on the wheel: countdown of 2, 3 or 5 seconds, "Wait for me", or "Send immediately".

## Requirements

- Steam Deck with SteamOS (tested on the OLED model); Desktop Mode for the installation, then play in Game
  or Desktop Mode
- WoW Forever (Classic-based client) through Proton
- About 2 GB of free space

## Install

See **[Installation](docs/install.md)**. It takes about 10 minutes, including a one-time controller setting.

## More

- [Lab report](docs/lab-report.md): every model, engine and setting we tested, with all results
- [Run the tests yourself](docs/run-the-tests.md): record your own voice and compare models on it

## Credits

Speech model: NVIDIA Parakeet unified-en 0.6B (CC-BY-4.0), as the
[GGUF build by handy-computer](https://huggingface.co/handy-computer/parakeet-unified-en-0.6b-gguf), run by
[transcribe.cpp](https://pypi.org/project/transcribe-cpp/) on Vulkan. Pause detection: Silero VAD (MIT), via
sherpa-onnx (Apache-2.0). Built by a WoW player together with Claude (Anthropic).
Our code: [MIT licence](LICENSE). The speech model keeps its own licence (CC-BY-4.0).
Not affiliated with Blizzard Entertainment or Valve.
