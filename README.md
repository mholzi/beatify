# Beatify

A Home Assistant integration for hosting music guessing party games using Music Assistant.

## Features

- Party game where players guess the release year of songs
- Works with Music Assistant for music playback
- Mobile-friendly player interface via QR code
- Real-time scoring and leaderboards

## Requirements

- Home Assistant 2025.11+
- Music Assistant 2.4+ integration installed and configured

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu and select "Custom repositories"
3. Add this repository URL and select "Integration" as the category
4. Click "Install"
5. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/beatify` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to Settings > Devices & Services
2. Click "Add Integration"
3. Search for "Beatify"
4. Follow the setup wizard

## Troubleshooting

### HACS Installation Issues

**Integration not appearing after HACS install:**
- Ensure you've restarted Home Assistant after installation
- Check the Home Assistant logs for any errors
- Verify HACS shows the integration as "Installed"

**"Music Assistant not found" error:**
- Install and configure Music Assistant before setting up Beatify
- Ensure Music Assistant shows as "Loaded" in Settings > Devices & Services

**Integration not appearing in search:**
- Clear your browser cache
- Try searching for "beatify" (lowercase)
- Check that the `custom_components/beatify/` folder exists

## Development

This integration was bootstrapped from [integration_blueprint](https://github.com/ludeeus/integration_blueprint).

### Running Tests

```bash
pytest tests/
```

### Linting

```bash
ruff check custom_components/beatify/
```

## License

MIT
