# Doc Job Workstation

A private job board for documentary production work: producer, director, cinematographer, editor and fixer roles, with extra weight on China-related and Mandarin/English bilingual jobs.

It updates itself twice a day (09:00 and 22:00 Beijing time) on GitHub Actions. It pulls from film/TV, journalism, remote-work and China job boards, a watchlist of media employers' career pages, and (through JobSpy) LinkedIn, Indeed, Glassdoor, ZipRecruiter and Google Jobs. Each job gets a fit score, and the results are published as a password-protected dashboard on GitHub Pages.

- Setup and everyday use: **[SETUP.md](SETUP.md)**
- All settings (keywords, scoring, sources, filters, quick links): **[config.json](config.json)**

## Layout

```
config.json                     settings
fetcher/run.py                  runs every source, scores, merges, encrypts
fetcher/sources.py              one function per job source
fetcher/util.py                 scoring, location/workplace/employment detection, encryption
docs/                           the dashboard (GitHub Pages serves this folder)
  index.html, app.js, style.css
  data.enc                      encrypted job pool (written by the workflow)
  meta.json                     last-update time and counts (no job data)
.github/workflows/update-jobs.yml   the twice-daily schedule
```

## Run locally (optional)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SITE_PASSWORD=yourpassword .venv/bin/python fetcher/run.py      # or omit SITE_PASSWORD to write plain docs/data.json
cd docs && python3 -m http.server 8000                          # then open http://localhost:8000
```
