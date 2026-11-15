from flask import Flask, render_template, request, abort, redirect, url_for
import pandas as pd
import gzip
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
PHOTO_DIR = BASE / 'static' / 'photos'

app = Flask(__name__)

scores = pd.read_csv(DATA / 'scores.csv')
interests = pd.read_csv(gzip.open(DATA / 'interests.csv.gz', 'rt', encoding='utf-8'), low_memory=False)

# Clean common display fields
scores['Member'] = scores['Member'].fillna('Unknown')
scores['Party'] = scores['Party'].fillna('Unknown')
interests['Member'] = interests['Member'].fillna('Unknown')
interests['Category'] = interests['Category'].fillna('Other')
interests['Register Date'] = interests['Register Date'].fillna('')
interests['Interest Description'] = interests['Interest Description'].fillna('')

CATEGORY_ORDER = [
    'Donations', 'Employment', 'Gifts', 'Overseas', 'Property',
    'Shareholdings', 'Family', 'Miscellaneous'
]

# Global ranking: higher score first; ties are broken by lower raw penalty, then name.
_ranked_scores = scores.copy()
_ranked_scores = _ranked_scores.sort_values(
    ['Final Score', 'Total Raw Penalty', 'Member'],
    ascending=[False, True, True],
    kind='mergesort'
).reset_index(drop=True)
_ranked_scores['Rank'] = range(1, len(_ranked_scores) + 1)
RANKS = dict(zip(_ranked_scores['Mnis Id'], _ranked_scores['Rank']))


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


@app.route('/photo/<int:mnis_id>')
def mp_photo(mnis_id):
    """Serve the local portrait when available; otherwise fall back to Parliament."""
    local = PHOTO_DIR / f'{mnis_id}.jpg'
    if local.exists() and local.stat().st_size > 1000:
        return redirect(url_for('static', filename=f'photos/{mnis_id}.jpg'))
    return redirect(
        f'https://members-api.parliament.uk/api/Members/{mnis_id}/Portrait'
        '?cropType=ThreeFour&webVersion=true'
    )


@app.route('/')
def home():
    total_mps = len(scores)
    total_interests = len(interests)
    register_count = interests['Register ID'].nunique()
    rectifications = int(scores['Rectification Count'].sum())
    update_file = DATA / 'last_update.txt'
    last_update = update_file.read_text(encoding='utf-8') if update_file.exists() else ''
    return render_template(
        'home.html',
        total_mps=total_mps,
        total_interests=total_interests,
        register_count=register_count,
        rectifications=rectifications,
        last_update=last_update,
    )


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
    return render_template(
        'mps.html',
        mps=[dict(x, Rank=RANKS.get(x['Mnis Id'])) for x in df.to_dict('records')],
        parties=parties,
        categories=CATEGORY_ORDER,
        q=q,
        selected_party=party,
        selected_category=category,
        selected_sort=sort,
    )


@app.route('/mp/<int:mnis_id>')
def mp_profile(mnis_id):
    row = mp_row(mnis_id)
    if row is None:
        abort(404)

    mp_interests = interests[interests['Mnis Id'] == mnis_id].copy()
    mp_interests = mp_interests.sort_values(['Register Date', 'Interest ID'], ascending=[False, False])

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
    category_breakdown = [(name, row[col]) for name, col in category_cols.items()]
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


@app.route('/rankings')
def rankings():
    return render_template('rankings.html', rankings=_ranked_scores.to_dict('records'))


@app.route('/methodology')
def methodology():
    return render_template('methodology.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(debug=True)
