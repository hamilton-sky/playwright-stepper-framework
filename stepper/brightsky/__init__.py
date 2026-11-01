"""
stepper/brightsky/ — the BrightSky verification adapter.

Fetches BrightSky workflow versions with a bridge token, runs them through the
stepper pipeline and reports each run back. It sits beside `stepper/engine/`,
not under `stepper/sites/`: BrightSky is a backend to talk to, not a site.
"""
