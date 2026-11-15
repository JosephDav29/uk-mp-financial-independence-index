
from flask import Flask, render_template, request, abort, redirect, url_for
import pandas as pd
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
PHOTO_DIR = BASE / 'static' / 'photos'

app = Flask(__name__)


# --------------------------------------------------
# LOAD MP SCORES
# --------------------------------------------------

scores = pd.read_csv(DATA / 'scores.csv')

scores['Member'] = scores['Member'].fillna('Unknown')
scores['Party'] = scores['Party'].fillna('Unknown')

# Make MP IDs consistent between the two datasets.
scores['Mnis Id'] = pd.to_numeric(
    scores['Mnis Id'], errors='coerce'
).astype('Int64')


# --------------------------------------------------
# LOAD ONLY THE INTEREST COLUMNS THE WEBSITE NEEDS
# --------------------------------------------------

interests_file = DATA / 'interests.csv.gz'

# These are the only original columns needed by the website.
required_columns = {
    'Mnis Id',
    'Member',
    'Category',
    'Id',
    '_Register_ID',
    '_Register_Date',
    'Register ID',
    'Register Date',
    'Interest ID',
    'Interest Description',
    'Summary',
}

# Also include the latest-version register date and summary columns.
version_pattern = re.compile(
    r'^Version\s*\d+\s+(Register Date|Summary)$',
    flags=re.IGNORECASE
)


def keep_interest_column(column):
    """Only load columns needed to display MP interests."""
    column = str(column)

    if column in required_columns:
        return True

    if column.lower() in {x.lower() for x in required_columns}:
        return True

    return bool(version_pattern.match(column))


interests = pd.read_csv(
    interests_file,
    usecols=keep_interest_column
)

# Clean the fields used by the website.
if 'Member' not in interests.columns:
    interests['Member'] = 'Unknown'
else:
    interests['Member'] = interests['Member'].fillna('Unknown')

if 'Category' not in interests.columns:
    interests['Category'] = 'Other'
else:
    interests['Category'] = interests['Category'].fillna('Other')

# Convert MP IDs to numbers so they match the scores dataset.
interests['Mnis Id'] = pd.to_numeric(
    interests['Mnis Id'], errors='coerce'
).astype('Int64')


# --------------------------------------------------
# FIND THE LATEST VERSION OF A REGISTER FIELD
# --------------------------------------------------

def latest_version_column(df, field):
    columns = []

    pattern = re.compile(
        r'^Version\s*(\d+)\s+' + re.escape(field) + r'$',
        flags=re.IGNORECASE
    )

    for column in df.columns:
        match = pattern.match(str(column))

        if match:
            columns.append((int(match.group(1)), column))

    columns.sort(reverse=True)

    if not columns:
        return pd.Series('', index=df.index, dtype='object')

    result = pd.Series('', index=df.index, dtype='object')

    for version, column in columns:
        values = df[column].fillna('').astype(str)

        result = result.mask(
            result.eq('') & values.ne(''),
            values
        )

    return result


# --------------------------------------------------
# CREATE THE SIMPLIFIED WEBSITE COLUMNS
# --------------------------------------------------

if 'Register Date' not in interests.columns:
    interests['Register Date'] = latest_version_column(
        interests, 'Register Date'
    )

if '_Register_Date' in interests.columns:
    interests['Register Date'] = interests['Register Date'].where(
        interests['Register Date'].ne(''),
        interests['_Register_Date'].fillna('').astype(str)
    )

if 'Interest Description' not in interests.columns:
    interests['Interest Description'] = latest_version_column(
        interests, 'Summary'
    )

if 'Summary' in interests.columns:
    interests['Interest Description'] = interests[
        'Interest Description'
    ].where(
        interests['Interest Description'].ne(''),
        interests['Summary'].fillna('').astype(str)
    )

if 'Interest ID' not in interests.columns:
    if 'Id' in interests.columns:
        interests['Interest ID'] = interests['Id']
    else:
        interests['Interest ID'] = ''

if 'Register ID' not in interests.columns:
    if '_Register_ID' in interests.columns:
        interests['Register ID'] = interests['_Register_ID']
    else:
        interests['Register ID'] = ''

interests['Register Date'] = interests['Register Date'].fillna('')
interests['Interest Description'] = interests[
    'Interest Description'
].fillna('')


# --------------------------------------------------
# WEBSITE SETTINGS
# --------------------------------------------------

CATEGORY_ORDER = [
    'Donations',
    'Employment',
    'Gifts',
    'Overseas',
    'Property',
    'Shareholdings',
    'Family',
    'Miscellaneous'
]


# --------------------------------------------------
# RANK THE MPs
# --------------------------------------------------

_ranked_scores = scores.sort_values(
    ['Final Score', 'Total Raw Penalty', 'Member'],
    ascending=[False, True, True],
    kind='mergesort'
).reset_index(drop=True)

_ranked_scores['Rank'] = range(1, len(_ranked_scores) + 1)

RANKS = {
    int(row['Mnis Id']): int(row['Rank'])
    for _, row in _ranked_scores.iterrows()
    if pd.notna(row['Mnis Id'])
}


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def mp_row(mnis_id):
    rows = scores[scores['Mnis Id'] == mnis_id]

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def score_breakdown(row):
    return [
        ('Donations & political support', row['Donations Penalty']),
        ('Employment & earnings', row['Employment Penalty']),
        ('Gifts & hospitality', row['Gifts Penalty']),
        ('Overseas visits', row['Overseas Penalty']),
        ('Property', row['Property Penalty']),
        ('Shareholdings', row['Shareholdings Penalty']),
        ('Family interests', row['Family Penalty']),
        ('Miscellaneous interests', row['Miscellaneous Penalty']),
        ('Concentration', row['Concentration Penalty']),
        ('Transparency', row['Transparency Penalty']),
    ]


@app.template_filter('mid')
def mid_filter(value):
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------
# MP PHOTO
# --------------------------------------------------

@app.route('/photo/<int:mnis_id>')
def mp_photo(mnis_id):
    """Serve a local portrait when available."""

    local = PHOTO_DIR / f'{mnis_id}.jpg'

    if local.exists() and local.stat().st_size > 1000:
        return redirect(
            url_for('static', filename=f'photos/{mnis_id}.jpg')
        )

    return redirect(
        f'https://members-api.parliament.uk/api/Members/{mnis_id}/Portrait'
        '?cropType=ThreeFour&webVersion=true'
    )


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route('/')
def home():
    total_mps = len(scores)
    total_interests = len(interests)
    register_count = interests['Register ID'].nunique()

    rectifications = int(scores['Rectification Count'].sum())

    update_file = DATA / 'last_update.txt'

    last_update = (
        update_file.read_text(encoding='utf-8')
        if update_file.exists()
        else ''
    )

    return render_template(
        'home.html',
        total_mps=total_mps,
        total_interests=total_interests,
        register_count=register_count,
        rectifications=rectifications,
        last_update=last_update,
    )


# --------------------------------------------------
# MP LIST
# --------------------------------------------------

@app.route('/mps')
def mps():
    q = request.args.get('q', '').strip()
    party = request.args.get('party', '').strip()
    category = request.args.get('category', '').strip()
    sort = request.args.get('sort', 'name')

    df = scores.copy()

    if q:
        mask = (
            df['Member'].str.contains(q, case=False, na=False)
            | df['Party'].str.contains(q, case=False, na=False)
        )

        df = df[mask]

    if party:
        df = df[df['Party'] == party]

    if category:
        category_map = {
            'Donations': 'Donations Penalty',
            'Employment': 'Employment Penalty',
            'Gifts': 'Gifts Penalty',
            'Overseas': 'Overseas Penalty',
            'Property': 'Property Penalty',
            'Shareholdings': 'Shareholdings Penalty',
            'Family': 'Family Penalty',
            'Miscellaneous': 'Miscellaneous Penalty',
        }

        col = category_map.get(category)

        if col:
            df = df[df[col] > 0]

    if sort == 'score_high':
        df = df.sort_values('Final Score', ascending=False)

    elif sort == 'score_low':
        df = df.sort_values('Final Score', ascending=True)

    else:
        df = df.sort_values('Member')

    parties = sorted(scores['Party'].dropna().unique())

    mp_list = [
        dict(x, Rank=RANKS.get(x['Mnis Id']))
        for x in df.to_dict('records')
    ]

    return render_template(
        'mps.html',
        mps=mp_list,
        parties=parties,
        categories=CATEGORY_ORDER,
        q=q,
        selected_party=party,
        selected_category=category,
        selected_sort=sort,
    )


# --------------------------------------------------
# INDIVIDUAL MP PROFILE
# --------------------------------------------------

@app.route('/mp/<int:mnis_id>')
def mp_profile(mnis_id):
    row = mp_row(mnis_id)

    if row is None:
        abort(404)

    mp_interests = interests[
        interests['Mnis Id'] == mnis_id
    ].copy()

    mp_interests = mp_interests.sort_values(
        ['Register Date', 'Interest ID'],
        ascending=[False, False]
    )

    category_cols = {
        'Donations': 'Donations Penalty',
        'Employment': 'Employment Penalty',
        'Gifts': 'Gifts Penalty',
        'Overseas': 'Overseas Penalty',
        'Property': 'Property Penalty',
        'Shareholdings': 'Shareholdings Penalty',
        'Family': 'Family Penalty',
        'Miscellaneous': 'Miscellaneous Penalty',
    }

    category_breakdown = [
        (name, row[col])
        for name, col in category_cols.items()
    ]

    entries = mp_interests.head(150).to_dict('records')

    return render_template(
        'profile.html',
        mp=row,
        rank=RANKS.get(mnis_id),
        breakdown=score_breakdown(row),
        category_breakdown=category_breakdown,
        entries=entries,
        total_entries=len(mp_interests),
    )


# --------------------------------------------------
# RANKINGS
# --------------------------------------------------

@app.route('/rankings')
def rankings():
    return render_template(
        'rankings.html',
        rankings=_ranked_scores.to_dict('records')
    )


# --------------------------------------------------
# METHODOLOGY
# --------------------------------------------------

@app.route('/methodology')
def methodology():
    return render_template('methodology.html')


# --------------------------------------------------
# ABOUT
# --------------------------------------------------

@app.route('/about')
def about():
    return render_template('about.html')


# --------------------------------------------------
# 404 ERROR PAGE
# --------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


# --------------------------------------------------
# RUN LOCALLY
# --------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)
