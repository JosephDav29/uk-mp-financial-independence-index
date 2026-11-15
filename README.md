# UK MP's Financial Independence Index

A Flask website presenting a transparent, reproducible scoring methodology applied to the UK Parliament Register of Members' Financial Interests.

## Automatic updates

`update_data.py` downloads published Commons Registers from the official UK Parliament Register API, recalculates interest-level penalties and rebuilds all MP scores. The included GitHub Actions workflow runs every day and can also be run manually.

The live site can be connected to the GitHub repository on Render. Render automatically redeploys when the workflow commits updated data.

## Local run

```text
python -m pip install -r requirements.txt
python download_photos.py
python app.py
```

## Automatic update locally

```text
python update_data.py
```

## Methodology

The site's UK-specific methodology is documented on `/methodology`. The project was inspired in part by the US Political Integrity Index, but the UK scoring rules are independently defined for the UK Parliament register structure.

Official UK Parliament sources:
- Register API: https://interests-api.parliament.uk/index.html
- Register archive: https://members.parliament.uk/members/commons/interests/publications
