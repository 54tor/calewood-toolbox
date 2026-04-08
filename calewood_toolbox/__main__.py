from .cli import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Common when piping to `head`/`rg` and the consumer closes early.
        raise SystemExit(0)
