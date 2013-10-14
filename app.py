import psycopg2, md5, random, urlparse, os, re, json, jinja2, shlex, time
from flask import Flask, url_for, request, redirect, render_template, g, send_from_directory, abort, Response
from flask.ext.assets import Environment, Bundle
from werkzeug import secure_filename
from htmlmin.minify import html_minify

# ======================================================================

app = Flask(__name__)
app.config.update(
    SECRET_KEY='6ffaf816037f37552577fd8deee81fd0'
    )

assets = Environment(app)

if 'DATABASE_URL' in os.environ:
    urlparse.uses_netloc.append('postgres')
    database_url = urlparse.urlparse(os.environ['DATABASE_URL'])
    database = 'host={0} port={1} dbname={2} user={3} password={4}'.format(
        database_url.hostname, database_url.port,
        database_url.path[1:], database_url.username, database_url.password)
else:
    database = 'dbname=worldofe host=localhost'

# ======================================================================

@app.before_request
def before_request():
    g.db = psycopg2.connect(database)

@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'):
        g.db.close()

# ======================================================================

@app.route('/data')
def data():
    ''' serve json for app '''
    return Response(open('data.json').read(), mimetype='application/json')

@app.route('/', methods=['GET'])
def home():
    ''' serve home page '''
    data = open('data.json').read()
    html = render_template('index.html', data=json.loads(data))
    return html_minify(html)

@app.errorhandler(404)
def page_not_found(e):
    html = render_template('error.html', message='Page not found.')
    return html_minify(html), 404

@app.errorhandler(500)
def server_error(e):
    html = render_template('error.html', message='Application error.')
    return html_minify(html), 500

# ======================================================================

if __name__ == '__main__':
    if 'PORT' in os.environ:
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    else:
        app.run(debug=True)
