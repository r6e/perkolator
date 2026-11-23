# Security

## Reporting a vulnerability

Report it privately through GitHub: on this repository's **Security** tab,
choose **Report a vulnerability**. Please do not open a public issue for it.

Say what you found, how to reproduce it and what it lets someone do. Expect a
first reply within a week.

## What is in scope

Only the latest commit on `main` is supported. The parts most worth a look:

- the workflows under `.github/workflows/`, which hold the repository's write
  access and the model credential;
- the scripts under `scripts/`, which keep model output and credentials out
  of the public logs and the published data;
- the watcher prompt and the data schema, which decide what text a model
  that has read an untrusted web page can put in the data files;
- the feed builder, which turns the data files into what subscribers'
  calendars show.

The benefit data itself being out of date or wrong is not a vulnerability;
open an ordinary issue for that.
