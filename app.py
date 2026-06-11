import sqlite3
import os
import random
import string
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'wc2026-secret-change-me')
DATABASE = 'worldcup.db'

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            favorite_teams TEXT DEFAULT '',
            golden_boot TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS groups_ (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            invite_code TEXT UNIQUE NOT NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups_(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            role TEXT DEFAULT 'member',
            UNIQUE(group_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            home_team TEXT NOT NULL,
            home_team_name TEXT NOT NULL,
            away_team TEXT NOT NULL,
            away_team_name TEXT NOT NULL,
            kickoff TEXT NOT NULL,
            stage TEXT NOT NULL,
            group_name TEXT,
            venue TEXT,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT DEFAULT 'scheduled'
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            match_id TEXT REFERENCES matches(id) ON DELETE CASCADE,
            predicted_home INTEGER NOT NULL,
            predicted_away INTEGER NOT NULL,
            points_earned INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, match_id)
        );

        CREATE TABLE IF NOT EXISTS bracket_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            group_id INTEGER REFERENCES groups_(id) ON DELETE CASCADE,
            round TEXT NOT NULL,
            slot INTEGER NOT NULL,
            team_code TEXT,
            team_name TEXT,
            UNIQUE(user_id, group_id, round, slot)
        );

        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups_(id) ON DELETE CASCADE,
            challenger_id INTEGER REFERENCES users(id),
            challenged_id INTEGER REFERENCES users(id),
            match_id TEXT REFERENCES matches(id),
            description TEXT NOT NULL,
            stakes TEXT NOT NULL,
            challenger_pick TEXT NOT NULL,
            challenged_pick TEXT,
            status TEXT DEFAULT 'pending',
            winner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups_(id) ON DELETE CASCADE,
            match_id TEXT REFERENCES matches(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    ''')

    # Seed matches if empty
    if not db.execute('SELECT 1 FROM matches LIMIT 1').fetchone():
        db.executescript('''
        INSERT OR IGNORE INTO matches VALUES
        ('WC26-A1','MEX','Mexico','ECU','Ecuador','2026-06-11 23:00','group','A','SoFi Stadium, LA',NULL,NULL,'scheduled'),
        ('WC26-A2','CAN','Canada','COL','Colombia','2026-06-13 22:00','group','A','BMO Field, Toronto',NULL,NULL,'scheduled'),
        ('WC26-A3','MEX','Mexico','CAN','Canada','2026-06-17 22:00','group','A','AT&T Stadium, Dallas',NULL,NULL,'scheduled'),
        ('WC26-A4','COL','Colombia','ECU','Ecuador','2026-06-17 02:00','group','A','Levis Stadium, SF',NULL,NULL,'scheduled'),
        ('WC26-B1','ARG','Argentina','NGA','Nigeria','2026-06-12 22:00','group','B','MetLife Stadium, NJ',NULL,NULL,'scheduled'),
        ('WC26-B2','CHI','Chile','PER','Peru','2026-06-13 02:00','group','B','Rose Bowl, LA',NULL,NULL,'scheduled'),
        ('WC26-C1','USA','United States','CRI','Costa Rica','2026-06-12 02:00','group','C','SoFi Stadium, LA',NULL,NULL,'scheduled'),
        ('WC26-C2','URU','Uruguay','BOL','Bolivia','2026-06-13 00:00','group','C','AT&T Stadium, Dallas',NULL,NULL,'scheduled'),
        ('WC26-D1','GER','Germany','CRO','Croatia','2026-06-12 00:00','group','D','Empower Field, Denver',NULL,NULL,'scheduled'),
        ('WC26-D2','MAR','Morocco','KSA','Saudi Arabia','2026-06-14 02:00','group','D','Allegiant Stadium, LV',NULL,NULL,'scheduled'),
        ('WC26-E1','ESP','Spain','NED','Netherlands','2026-06-14 22:00','group','E','Hard Rock Stadium, Miami',NULL,NULL,'scheduled'),
        ('WC26-E2','BEL','Belgium','VNM','Vietnam','2026-06-15 02:00','group','E','Levis Stadium, SF',NULL,NULL,'scheduled'),
        ('WC26-F1','FRA','France','TUN','Tunisia','2026-06-15 22:00','group','F','MetLife Stadium, NJ',NULL,NULL,'scheduled'),
        ('WC26-F2','POR','Portugal','ALG','Algeria','2026-06-16 02:00','group','F','SoFi Stadium, LA',NULL,NULL,'scheduled'),
        ('WC26-G1','BRA','Brazil','PAR','Paraguay','2026-06-16 22:00','group','G','AT&T Stadium, Dallas',NULL,NULL,'scheduled'),
        ('WC26-G2','ENG','England','SEN','Senegal','2026-06-17 00:00','group','G','MetLife Stadium, NJ',NULL,NULL,'scheduled');
        ''')
    db.commit()
    db.close()

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user():
    uid = session.get('user_id')
    if uid:
        return query('SELECT * FROM users WHERE id=?', [uid], one=True)
    return None

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def calc_points(ph, pa, ah, aa):
    if ph == ah and pa == aa:
        return 3
    if (ph > pa) == (ah > aa) and (ph == pa) == (ah == aa):
        return 1
    return 0

TEAMS = {
    'MEX':{'name':'Mexico','flag':'🇲🇽'},
    'ECU':{'name':'Ecuador','flag':'🇪🇨'},
    'CAN':{'name':'Canada','flag':'🇨🇦'},
    'COL':{'name':'Colombia','flag':'🇨🇴'},
    'ARG':{'name':'Argentina','flag':'🇦🇷'},
    'NGA':{'name':'Nigeria','flag':'🇳🇬'},
    'CHI':{'name':'Chile','flag':'🇨🇱'},
    'PER':{'name':'Peru','flag':'🇵🇪'},
    'USA':{'name':'United States','flag':'🇺🇸'},
    'CRI':{'name':'Costa Rica','flag':'🇨🇷'},
    'URU':{'name':'Uruguay','flag':'🇺🇾'},
    'BOL':{'name':'Bolivia','flag':'🇧🇴'},
    'GER':{'name':'Germany','flag':'🇩🇪'},
    'CRO':{'name':'Croatia','flag':'🇭🇷'},
    'MAR':{'name':'Morocco','flag':'🇲🇦'},
    'KSA':{'name':'Saudi Arabia','flag':'🇸🇦'},
    'ESP':{'name':'Spain','flag':'🇪🇸'},
    'NED':{'name':'Netherlands','flag':'🇳🇱'},
    'BEL':{'name':'Belgium','flag':'🇧🇪'},
    'VNM':{'name':'Vietnam','flag':'🇻🇳'},
    'FRA':{'name':'France','flag':'🇫🇷'},
    'TUN':{'name':'Tunisia','flag':'🇹🇳'},
    'POR':{'name':'Portugal','flag':'🇵🇹'},
    'ALG':{'name':'Algeria','flag':'🇩🇿'},
    'BRA':{'name':'Brazil','flag':'🇧🇷'},
    'PAR':{'name':'Paraguay','flag':'🇵🇾'},
    'ENG':{'name':'England','flag':'🏴󠁧󠁢󠁥󠁮󠁧󠁿'},
    'SEN':{'name':'Senegal','flag':'🇸🇳'},
    'JPN':{'name':'Japan','flag':'🇯🇵'},
    'KOR':{'name':'South Korea','flag':'🇰🇷'},
    'AUS':{'name':'Australia','flag':'🇦🇺'},
    'CMR':{'name':'Cameroon','flag':'🇨🇲'},
    'GHA':{'name':'Ghana','flag':'🇬🇭'},
    'EGY':{'name':'Egypt','flag':'🇪🇬'},
    'DEN':{'name':'Denmark','flag':'🇩🇰'},
    'SUI':{'name':'Switzerland','flag':'🇨🇭'},
    'POL':{'name':'Poland','flag':'🇵🇱'},
    'IRN':{'name':'Iran','flag':'🇮🇷'},
    'VEN':{'name':'Venezuela','flag':'🇻🇪'},
    'PAN':{'name':'Panama','flag':'🇵🇦'},
    'JAM':{'name':'Jamaica','flag':'🇯🇲'},
}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        if not name or not email:
            return render_template('login.html', error='Name and email required')
        user = query('SELECT * FROM users WHERE email=?', [email], one=True)
        if not user:
            execute('INSERT INTO users (name, email) VALUES (?,?)', [name, email])
            user = query('SELECT * FROM users WHERE email=?', [email], one=True)
        session['user_id'] = user['id']
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    matches = query("SELECT * FROM matches WHERE status != 'finished' ORDER BY kickoff LIMIT 6")
    preds = {p['match_id']: p for p in query('SELECT * FROM predictions WHERE user_id=?', [user['id']])}
    groups = query('''SELECT g.* FROM groups_ g
                      JOIN group_members gm ON g.id=gm.group_id
                      WHERE gm.user_id=? LIMIT 5''', [user['id']])
    total_pts = sum(p['points_earned'] or 0 for p in query('SELECT points_earned FROM predictions WHERE user_id=?', [user['id']]))
    fav_teams = [t for t in (user['favorite_teams'] or '').split(',') if t]
    return render_template('dashboard.html', user=user, matches=matches, preds=preds,
                           groups=groups, total_pts=total_pts, fav_teams=fav_teams, TEAMS=TEAMS)

@app.route('/matches')
@login_required
def matches():
    user = current_user()
    all_matches = query('SELECT * FROM matches ORDER BY kickoff')
    preds = {p['match_id']: p for p in query('SELECT * FROM predictions WHERE user_id=?', [user['id']])}
    return render_template('matches.html', matches=all_matches, preds=preds, TEAMS=TEAMS)

@app.route('/matches/<match_id>', methods=['GET', 'POST'])
@login_required
def match_detail(match_id):
    user = current_user()
    match = query('SELECT * FROM matches WHERE id=?', [match_id], one=True)
    if not match:
        return 'Match not found', 404

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'predict' and match['status'] == 'scheduled':
            ph = int(request.form['home'])
            pa = int(request.form['away'])
            execute('''INSERT INTO predictions (user_id, match_id, predicted_home, predicted_away)
                       VALUES (?,?,?,?) ON CONFLICT(user_id,match_id)
                       DO UPDATE SET predicted_home=excluded.predicted_home,
                                     predicted_away=excluded.predicted_away''',
                    [user['id'], match_id, ph, pa])
        elif action == 'comment':
            content = request.form.get('content', '').strip()[:500]
            group_id = request.form.get('group_id')
            if content and group_id:
                execute('INSERT INTO comments (group_id,match_id,user_id,content) VALUES (?,?,?,?)',
                        [group_id, match_id, user['id'], content])
        return redirect(url_for('match_detail', match_id=match_id))

    pred = query('SELECT * FROM predictions WHERE user_id=? AND match_id=?', [user['id'], match_id], one=True)
    groups = query('''SELECT g.* FROM groups_ g JOIN group_members gm ON g.id=gm.group_id
                      WHERE gm.user_id=?''', [user['id']])
    first_group = groups[0] if groups else None
    comments = []
    group_preds = []
    if first_group:
        comments = query('''SELECT c.*, u.name FROM comments c JOIN users u ON c.user_id=u.id
                            WHERE c.match_id=? AND c.group_id=? ORDER BY c.created_at''',
                         [match_id, first_group['id']])
        member_ids = [m['user_id'] for m in query('SELECT user_id FROM group_members WHERE group_id=?', [first_group['id']])]
        if member_ids:
            placeholders = ','.join('?' * len(member_ids))
            group_preds = query(f'''SELECT p.*, u.name FROM predictions p
                                    JOIN users u ON p.user_id=u.id
                                    WHERE p.match_id=? AND p.user_id IN ({placeholders})''',
                                [match_id] + member_ids)
    return render_template('match.html', match=match, pred=pred, groups=groups,
                           first_group=first_group, comments=comments,
                           group_preds=group_preds, TEAMS=TEAMS, user=user)

@app.route('/groups', methods=['GET', 'POST'])
@login_required
def groups():
    user = current_user()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form['name'].strip()
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            execute('INSERT INTO groups_ (name, invite_code, created_by) VALUES (?,?,?)',
                    [name, code, user['id']])
            gid = query('SELECT id FROM groups_ WHERE invite_code=?', [code], one=True)['id']
            execute('INSERT INTO group_members (group_id, user_id, role) VALUES (?,?,?)',
                    [gid, user['id'], 'admin'])
            return redirect(url_for('group_detail', group_id=gid))
        elif action == 'join':
            code = request.form['code'].strip().upper()
            grp = query('SELECT * FROM groups_ WHERE invite_code=?', [code], one=True)
            if not grp:
                my_groups = query('''SELECT g.* FROM groups_ g JOIN group_members gm ON g.id=gm.group_id
                                     WHERE gm.user_id=?''', [user['id']])
                return render_template('groups.html', groups=my_groups, error='Invalid invite code')
            try:
                execute('INSERT INTO group_members (group_id,user_id) VALUES (?,?)', [grp['id'], user['id']])
            except Exception:
                pass
            return redirect(url_for('group_detail', group_id=grp['id']))
    my_groups = query('''SELECT g.* FROM groups_ g JOIN group_members gm ON g.id=gm.group_id
                         WHERE gm.user_id=? ORDER BY gm.id DESC''', [user['id']])
    return render_template('groups.html', groups=my_groups)

@app.route('/groups/<int:group_id>')
@login_required
def group_detail(group_id):
    user = current_user()
    mem = query('SELECT * FROM group_members WHERE group_id=? AND user_id=?', [group_id, user['id']], one=True)
    if not mem:
        return 'Not a member', 403
    grp = query('SELECT * FROM groups_ WHERE id=?', [group_id], one=True)
    members = query('''SELECT u.*, gm.role FROM users u
                       JOIN group_members gm ON u.id=gm.user_id
                       WHERE gm.group_id=?''', [group_id])
    member_ids = [m['id'] for m in members]
    placeholders = ','.join('?' * len(member_ids))
    all_preds = query(f'SELECT * FROM predictions WHERE user_id IN ({placeholders})', member_ids)
    leaderboard = []
    for m in members:
        preds = [p for p in all_preds if p['user_id'] == m['id']]
        pts = sum(p['points_earned'] or 0 for p in preds)
        exact = sum(1 for p in preds if p['points_earned'] == 3)
        leaderboard.append({'user': m, 'points': pts, 'exact': exact, 'count': len(preds)})
    leaderboard.sort(key=lambda x: x['points'], reverse=True)
    bets = query('''SELECT b.*, u1.name as challenger_name, u2.name as challenged_name
                    FROM bets b
                    JOIN users u1 ON b.challenger_id=u1.id
                    JOIN users u2 ON b.challenged_id=u2.id
                    WHERE b.group_id=? ORDER BY b.created_at DESC''', [group_id])
    return render_template('group.html', grp=grp, members=members, leaderboard=leaderboard,
                           bets=bets, user=user, TEAMS=TEAMS)

@app.route('/groups/<int:group_id>/bet', methods=['POST'])
@login_required
def create_bet(group_id):
    user = current_user()
    execute('''INSERT INTO bets (group_id,challenger_id,challenged_id,description,stakes,challenger_pick)
               VALUES (?,?,?,?,?,?)''',
            [group_id, user['id'], request.form['challenged_id'],
             request.form['description'], request.form['stakes'], request.form['my_pick']])
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/bets/<int:bet_id>/respond', methods=['POST'])
@login_required
def respond_bet(bet_id):
    user = current_user()
    action = request.form['action']
    bet = query('SELECT * FROM bets WHERE id=?', [bet_id], one=True)
    if bet['challenged_id'] == user['id']:
        execute('UPDATE bets SET status=? WHERE id=?', [action, bet_id])
    return redirect(url_for('group_detail', group_id=bet['group_id']))

@app.route('/bets/<int:bet_id>/settle', methods=['POST'])
@login_required
def settle_bet(bet_id):
    bet = query('SELECT * FROM bets WHERE id=?', [bet_id], one=True)
    winner_id = request.form['winner_id']
    execute("UPDATE bets SET status='settled', winner_id=? WHERE id=?", [winner_id, bet_id])
    return redirect(url_for('group_detail', group_id=bet['group_id']))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()
    if request.method == 'POST':
        name = request.form['name'].strip()
        teams = ','.join(request.form.getlist('teams')[:4])
        golden = request.form.get('golden_boot', '').strip()
        execute('UPDATE users SET name=?, favorite_teams=?, golden_boot=? WHERE id=?',
                [name, teams, golden, user['id']])
        return redirect(url_for('profile'))
    fav_teams = [t for t in (user['favorite_teams'] or '').split(',') if t]
    stats = query('''SELECT COUNT(*) as cnt,
                            SUM(CASE WHEN points_earned=3 THEN 1 ELSE 0 END) as exact,
                            SUM(COALESCE(points_earned,0)) as pts
                     FROM predictions WHERE user_id=?''', [user['id']], one=True)
    return render_template('profile.html', user=user, fav_teams=fav_teams, TEAMS=TEAMS, stats=stats)

@app.route('/bracket')
@login_required
def bracket():
    user = current_user()
    groups = query('''SELECT g.* FROM groups_ g JOIN group_members gm ON g.id=gm.group_id
                      WHERE gm.user_id=?''', [user['id']])
    if not groups:
        return render_template('bracket.html', user=user, no_groups=True, TEAMS=TEAMS)
    grp = groups[0]
    my_picks = {f"{p['round']}_{p['slot']}": p for p in
                query('SELECT * FROM bracket_picks WHERE user_id=? AND group_id=?', [user['id'], grp['id']])}
    return render_template('bracket.html', user=user, grp=grp, my_picks=my_picks, TEAMS=TEAMS, no_groups=False)

@app.route('/bracket/save', methods=['POST'])
@login_required
def save_bracket():
    user = current_user()
    group_id = request.form['group_id']
    round_ = request.form['round']
    slots = int(request.form['slots'])
    for i in range(1, slots + 1):
        code = request.form.get(f'slot_{i}', '')
        name = TEAMS.get(code, {}).get('name', '') if code else ''
        execute('''INSERT INTO bracket_picks (user_id,group_id,round,slot,team_code,team_name)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,group_id,round,slot)
                   DO UPDATE SET team_code=excluded.team_code, team_name=excluded.team_name''',
                [user['id'], group_id, round_, i, code or None, name or None])
    return redirect(url_for('bracket'))

# Admin: update match score (password protected)
@app.route('/admin/result', methods=['POST'])
def admin_result():
    if request.form.get('admin_key') != os.environ.get('ADMIN_KEY', 'admin123'):
        return 'Unauthorized', 401
    match_id = request.form['match_id']
    hs = int(request.form['home_score'])
    as_ = int(request.form['away_score'])
    execute("UPDATE matches SET home_score=?, away_score=?, status='finished' WHERE id=?",
            [hs, as_, match_id])
    preds = query('SELECT * FROM predictions WHERE match_id=?', [match_id])
    for p in preds:
        pts = calc_points(p['predicted_home'], p['predicted_away'], hs, as_)
        execute('UPDATE predictions SET points_earned=? WHERE id=?', [pts, p['id']])
    return jsonify({'ok': True})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
