import psycopg2, psycopg2.extras, urlparse, os, sys, json, jinja2, time, datetime, itertools, re
from urlnorm import urlnorm
from flask import Flask, url_for, request, redirect, render_template, g, abort, flash
from flask.ext.login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug import secure_filename
from htmlmin.minify import html_minify
from micawber.providers import bootstrap_basic
from micawber.contrib.mcflask import add_oembed_filters

# ======================================================================

reload(sys)
sys.setdefaultencoding('utf-8')

app = Flask(__name__)
app.config.update(
    SECRET_KEY='6ffaf816037f37552577fd8deee81fd0'
    )

if 'DATABASE_URL' in os.environ:
    urlparse.uses_netloc.append('postgres')
    database_url = urlparse.urlparse(os.environ['DATABASE_URL'])
    database = 'host={0} port={1} dbname={2} user={3} password={4}'.format(
        database_url.hostname, database_url.port,
        database_url.path[1:], database_url.username, database_url.password)
else:
    database = 'dbname=spirehq host=localhost'

login_manager = LoginManager()
login_manager.init_app(app)

oembed_providers = bootstrap_basic()
add_oembed_filters(app, oembed_providers)

# ======================================================================

@app.before_request
def before_request():
    g.db = psycopg2.connect(database)

@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'):
        g.db.close()

@app.context_processor
def inject_globals():
    cur = g.db.cursor()
    cur.execute('SELECT key, value FROM metadata ORDER BY key ASC')
    data = dict(cur.fetchall())

    # fetch hierarchy of sections and categories
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('''
        SELECT categories.name AS cat_name, categories.slug AS cat_slug,
        sections.id, sections.next_id, sections.prev_id,
        sections.category, sections.slug, sections.name, sections.description,
        (SELECT COUNT(data_items) FROM data_items WHERE data_items.section=sections.id) as items_count
        FROM sections RIGHT JOIN categories ON sections.category=categories.id''')
    sections_data = cur.fetchall()
    cur.execute('''
        SELECT categories.name AS cat_name, categories.slug AS cat_slug,
        id, next_id, prev_id FROM categories''')
    categories_data = cur.fetchall()

    # group sections by category
    group_by_key = lambda a: a['cat_slug']
    sections_data.sort(key=group_by_key)
    sections = {}
    for cat, grp in itertools.groupby(sections_data, group_by_key):
        sections[cat] = ordered(list(grp))
    categories = [(cat['id'], cat['cat_slug'], sections[cat['cat_slug']])
                  for cat in ordered(categories_data)]

    data['categories'] = categories
    data['user'] = current_user
    return data

def delete_from_linkedlist(table, item_id):
    ''' remove a given node by id within a linked-list table '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # delete the selected row
    cur.execute('DELETE FROM ' + table + ' WHERE id=%s RETURNING prev_id, next_id',
                (item_id,))
    row = cur.fetchone()
    next_id = row['next_id']
    prev_id = row['prev_id']

    # splice its neighbors together
    if next_id and prev_id:
        cur.execute('UPDATE ' + table + ' SET next_id=%s WHERE id=%s', (next_id, prev_id))
        cur.execute('UPDATE ' + table + ' SET prev_id=%s WHERE id=%s', (prev_id, next_id))
    elif prev_id:
        cur.execute('UPDATE ' + table + ' SET next_id=0 WHERE id=%s', (prev_id,))
    elif next_id:
        cur.execute('UPDATE ' + table + ' SET prev_id=0 WHERE id=%s', (next_id,))
    g.db.commit()

def ordered(id_linked_list):
    ''' given unsorted linked-list node rows, returns a sorted listing '''
    by_itemid = {item.get('id'): item for item in id_linked_list}
    by_nextid = {item.get('next_id'): item for item in id_linked_list}
    by_previd = {item.get('prev_id'): item for item in id_linked_list}
    head = by_previd.get(0)
    tail = by_nextid.get(0)

    if len(id_linked_list) <= 1:
        return id_linked_list
    elif not head:
        flash('List error: missing head.')
        result = by_previd.values()
    elif not tail:
        flash('List error: missing tail.')
        result = by_previd.values()
    else:
        result = []
        next_item = head
        while next_item:
            result.append(next_item)
            next_id = next_item.get('next_id')
            next_item = by_itemid.get(next_id)
        if len(result) != len(id_linked_list):
            flash('List error: invalid order.')
            result = by_previd.values()
    return result

# ======================================================================

@login_required
@app.route('/edit', methods=['POST'])
def edit_hierarchy():
    ''' edit or delete a category '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # edit a category
    if request.form.get('edit') == 'edit':
        cat_id = request.form.get('cat_id')
        name = request.form.get('name')
        slug = slugify_category(name)

        if name:
            cur.execute(
                '''UPDATE categories SET name=%s, slug=%s WHERE id=%s''',
                (name, slug, cat_id))
            g.db.commit()
            flash('Category updated.')
        else:
            flash('Invalid request.')

    # delete a category
    elif request.form.get('delete') == 'delete':
        cat_id = request.form.get('cat_id')
        cur.execute(
            '''DELETE FROM data_items WHERE id IN
               (SELECT data_items.id FROM data_items JOIN sections
               ON data_items.section=sections.id WHERE sections.category=%s)''',
            (cat_id,))
        cur.execute('DELETE FROM sections WHERE category=%s', (cat_id,))
        delete_from_linkedlist('categories', cat_id)
        g.db.commit()
        flash('Category deleted.')

    return redirect(url_for('home'))

@login_required
@app.route('/new', methods=['POST'])
def add_hierarchy():
    ''' add a category or a section '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # add a category
    if request.form.get('type') == 'category':
        name = request.form.get('name')
        slug = slugify_category(name)

        if name:
            cur.execute(
                '''INSERT INTO categories (name, slug, prev_id, next_id)
                   VALUES (%s, %s, (SELECT COALESCE(MAX(id), 0) FROM categories), 0)
                   RETURNING prev_id, id''',
                (name, slug))
            row = cur.fetchone()
            cur.execute(
                '''UPDATE categories SET next_id=%s WHERE id=%s''',
                (row['id'], row['prev_id']))
            g.db.commit()
            flash('Category added.')
        else:
            flash('Invalid request.')

        return redirect(url_for('home'))

    # add a section
    elif request.form.get('type') == 'section':
        name = request.form.get('name')
        desc = request.form.get('description')
        section_slug = slugify_section(name)
        category_slug = request.form.get('category')

        if name:
            cur.execute(
                '''INSERT INTO sections (category, name, slug, description, prev_id, next_id)
                   VALUES ((SELECT id FROM categories WHERE slug=%s), %s, %s, %s,
                   (SELECT COALESCE(MAX(id), 0) FROM sections
                   WHERE category=(SELECT id FROM categories WHERE slug=%s)), 0)
                   RETURNING prev_id, id''',
                (category_slug, name, section_slug, desc, category_slug))
            row = cur.fetchone()
            cur.execute(
                '''UPDATE sections SET next_id=%s WHERE id=%s''',
                (row['id'], row['prev_id']))
            g.db.commit()
            flash('Section added.')
        else:
            flash('Invalid request.')

        return redirect(url_for('page', category_slug=category_slug, section_slug=section_slug))

    else:
        abort(400)

@app.route('/<category_slug>/<section_slug>', methods=['GET', 'POST'])
def page(category_slug, section_slug):
    ''' display all content in a given section '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if request.method == 'POST':

        # edit an entry in the section
        if request.form.get('item') and request.form.get('edit'):
            item_id = request.form.get('item')
            title = request.form.get('title')
            link = request.form.get('link')
            link = urlnorm(link) if link else None
            text = request.form.get('text')

            if title and text and current_user.is_active():
                cur.execute(
                    '''UPDATE data_items SET title=%s, link=%s, text=%s WHERE id=%s''',
                    (title, link, text, item_id))
                g.db.commit()
                flash('Item updated.')
            else:
                flash('Invalid request.')

        # delete an entry in the section
        elif request.form.get('item') and request.form.get('delete'):
            if current_user.is_active():
                item_id = request.form.get('item')
                delete_from_linkedlist('data_items', item_id)
                g.db.commit()
                flash('Item deleted.')
            else:
                flash('Invalid request.')

        # edit the section
        elif request.form.get('edit') == 'edit':
            sec_id = request.form.get('id')
            name = request.form.get('name')
            desc = request.form.get('description')
            section_slug = slugify_section(name, sec_id)

            if sec_id and name and current_user.is_active():
                cur.execute(
                    '''UPDATE sections SET name=%s, description=%s, slug=%s WHERE id=%s''',
                    (name, desc, section_slug, sec_id))
                g.db.commit()
                flash('Section updated.')
            else:
                flash('Invalid request.')

        # delete the section
        elif request.form.get('delete') == 'delete' and request.form.get('id'):
            sec_id = request.form.get('id')
            if current_user.is_active():
                delete_from_linkedlist('sections', sec_id)
                cur.execute('DELETE FROM data_items WHERE section=%s', (sec_id,))
                g.db.commit()
                flash('Section deleted.')
                return redirect(url_for('home'))
            else:
                flash('Invalid request.')

        # add an entry to the section
        else:
            title = request.form.get('title')
            link = request.form.get('link')
            link = urlnorm(link) if link else None
            text = request.form.get('text')

            if title and text and current_user.is_active():
                cur.execute(
                    '''INSERT INTO data_items (title, link, text, section)
                       VALUES (%s, %s, %s, (SELECT id FROM sections WHERE slug=%s))''',
                    (title, link, text, section_slug))
                g.db.commit()
                flash('Item added.')
            else:
                flash('Invalid request.')

    # retrieve the section metadata
    cur.execute(
        '''SELECT sections.id, sections.name, sections.description,
           categories.id AS cat_id, categories.name AS cat_name,
           (SELECT COUNT(data_items) FROM data_items WHERE data_items.section=sections.id) as items_count
           FROM sections JOIN categories ON sections.category=categories.id
           WHERE categories.slug=%s AND sections.slug=%s''',
        (category_slug, section_slug))
    section = cur.fetchone()
    if not section:
        abort(404)

    # retrieve the individual page of content
    cur.execute(
        '''SELECT data_items.id, data_items.prev_id, data_items.next_id,
           title, link, text, meta FROM data_items
           JOIN sections ON section=sections.id
           JOIN categories ON sections.category=categories.id
           WHERE categories.slug=%s AND sections.slug=%s
           ORDER BY data_items.id''',
        (category_slug, section_slug))
    content = ordered(cur.fetchall())

    # render the page
    return render_template(
        'content.html', section=section, content=content,
        category_slug=category_slug, section_slug=section_slug)

@login_required
@app.route('/feed', methods=['POST'])
def feed():
    ''' add or edit items in the newsfeed on the home page '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # edit an item in the feed
    if request.form.get('edit') == 'edit':
        item_id = request.form.get('item')
        title = request.form.get('title')
        link = request.form.get('link')
        text = request.form.get('text')

        if title and link and text:
            cur.execute(
                'UPDATE feed_items SET title=%s, link=%s, text=%s WHERE id=%s',
                (title, urlnorm(link), text, item_id))
            g.db.commit()
            flash('Item updated.')
        else:
            flash('Invalid request.')


        g.db.commit()

    # delete an item from the feed
    elif request.form.get('delete') == 'delete':
        item_id = request.form.get('item')
        cur.execute('DELETE FROM feed_items WHERE id=%s',
                    (item_id,))
        g.db.commit()
        flash('Item deleted.')

    # add an item to the feed
    else:
        title = request.form.get('title')
        link = request.form.get('link')
        text = request.form.get('text')
        created = datetime.datetime.now()
        published = datetime.datetime.now()

        if title and link and text:
            cur.execute(
                '''INSERT INTO feed_items
                   (title, link, text, created, published)
                   VALUES (%s, %s, %s, %s, %s)''',
                (title, urlnorm(link), text, created, published))
            g.db.commit()
            flash('Item added.')
        else:
            flash('Invalid request.')

    return redirect(url_for('home'))

@app.route('/')
def home():
    ''' serve home page '''
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # retrieve the latest feed items
    cur.execute('SELECT * FROM feed_items ORDER BY created DESC')
    feed_data = cur.fetchall()

    # render the page
    return render_template('index.html', feed=feed_data)

@app.errorhandler(404)
def page_not_found(e):
    html = render_template('error.html', message='Page not found.')
    return html_minify(html), 404

@app.errorhandler(500)
def server_error(e):
    html = render_template('error.html', message='Application error.')
    return html_minify(html), 500

# ======================================================================

class User(UserMixin):
    ''' dummy user type '''

    def __init__(self, userid):
        self.id = userid

@login_manager.user_loader
def load_user(userid):
    return User(userid)

@app.route('/login', methods=['POST'])
def login():
    cur = g.db.cursor()

    # retrieve credentials from the settings store
    cur.execute('SELECT key, value FROM metadata ORDER BY key ASC')
    data = dict(cur.fetchall())
    username = request.form.get('username')
    password = request.form.get('password')

    # if login is valid, log in the current user
    if username != data.get('username') or password != data.get('password'):
        flash('Invalid username or password.')
    else:
        user = User(0)
        login_user(user)
        flash('Logged in.')
    return redirect(url_for('home'))

@app.route('/logout', methods=['POST'])
def logout():

    # always log the user out
    logout_user()
    flash('Logged out.')
    return redirect(url_for('home'))

# ======================================================================

def slugify_category(name, category_id=None):
    ''' create a unique slug given a new category's name '''
    return slugify_generic(name, 'categories', category_id)

def slugify_section(name, section_id=None):
    ''' create a unique slug given a new section's name '''
    return slugify_generic(name, 'sections', section_id)

def slugify_generic(name, item_type, item_id=None):
    cur = g.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    base_slug = re.sub(r'[\W\_\s]+', '-', name.lower()).strip('-')
    cur.execute(
        'SELECT slug FROM ' + item_type + ' WHERE slug LIKE %s AND id != %s',
        (base_slug + '%', item_id or -1))
    similar_slugs = [row['slug'] for row in cur.fetchall()]
    i = 1
    slug = base_slug
    while slug in similar_slugs:
        i += 1
        slug = base_slug + '-' + str(i)
    return slug

# ======================================================================

@app.template_filter('domain')
def domain_filter(s):
    hostname = urlparse.urlparse(s).hostname
    if hostname.startswith('www.'):
        return hostname[4:]
    else:
        return hostname

@app.template_filter('format_date')
def format_date_filter(s):
    return datetime.datetime.strftime(s, '%-m/%-d')

if __name__ == '__main__':
    if 'PORT' in os.environ:
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    else:
        app.run(debug=True)
