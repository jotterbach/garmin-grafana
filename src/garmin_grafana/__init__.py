def main():
    # NOTE: this is a no-op -- see the packaged-entrypoint bug filed
    # alongside #12's lint-cleanup PR. Production runs
    # `python garmin_grafana/garmin_fetch.py` directly (Dockerfile CMD),
    # which triggers that file's own `if __name__ == "__main__"` block;
    # this function (the pip-installed `garmin-fetch` console script) is
    # a separate, currently broken path that was already a no-op before
    # this cleanup -- importing garmin_fetch here doesn't call anything.
    pass
