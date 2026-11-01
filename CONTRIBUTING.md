# Contributing

Contributions, bug reports, and feedback are welcome.

Useful places to help include ranking quality, support for more visual styles, reference-photo search, and the local browser app. Documentation fixes and small usability improvements are welcome too. Open an issue before starting a larger change so we can agree on the scope.

## Set up

Fork the repository and clone your fork, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web,dev]"
python -m pinterest_taste.web
```

Requires Python 3.10 or newer. On Windows, activate with `.venv\Scripts\activate`.

## Send a pull request

Keep changes focused and explain what they fix or improve. Include screenshots for visible UI changes and describe how you checked the result. Add or update tests when changing behaviour.

Run the test suite before submitting:

```bash
pytest
```

Tests use synthetic images and stub models without contacting Pinterest or downloading pretrained models. If you test live searches or models, describe those checks separately.

Never include browser cookies, credentials, downloaded photos, or private reference images in commits or issue reports.

## Report a bug

Include the steps to reproduce it, what you expected, what happened, and your operating system and Python version. Include relevant error output after removing personal information and credentials.

## License

By submitting a contribution, you agree that it will be available under this project's [MIT License](LICENSE).
