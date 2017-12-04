import os
import re
import random
import hashlib
import hmac
from string import letters
import logging
import time

import webapp2
import jinja2

from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir),
                               autoescape=True)
secret = 'katamari'


def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)


def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())


def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val


class BlogHandler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        return render_str(template, **params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))


def render_post(response, post):
    response.out.write('<b>' + post.subject + '</b><br>')
    response.out.write(post.content)


class MainPage(BlogHandler):
    def get(self):
        self.write('Hello, Udacity!')


# user stuff
def make_salt(length=5):
    return ''.join(random.choice(letters) for x in xrange(length))


def make_pw_hash(name, pw, salt=None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)


def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)


def users_key(group='default'):
    return db.Key.from_path('users', group)


class User(db.Model):
    name = db.StringProperty(required=True)
    pw_hash = db.StringProperty(required=True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent=users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email=None):
        pw_hash = make_pw_hash(name, pw)
        return User(parent=users_key(),
                    name=name,
                    pw_hash=pw_hash,
                    email=email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u

# blog stuff


def blog_key(name='default'):
    return db.Key.from_path('blogs', name)


class Post(db.Model):
    subject = db.StringProperty(required=True)
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    last_modified = db.DateTimeProperty(auto_now=True)
    author = db.StringProperty(required=True)
    likes = db.StringListProperty()

    def render(self):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str("post.html", post=self)


class BlogFront(BlogHandler):
    def get(self):
        posts = greetings = Post.all().order('-created')
        self.render('front.html', posts=posts)

    def post(self):
        id = self.request.get("id")
        self.redirect('/blog/%s' % id)


class MainPage(BlogHandler):
    def get(self):
        self.redirect("/blog")


class PostPage(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            return self.redirect('/blog')

        self.render("permalink.html", post=post)


class NewPost(BlogHandler):
    def get(self):
        if self.user:
            self.render("newpost.html")
        else:
            self.redirect("/login")

    def post(self):
        if not self.user:
            return self.redirect('/login')

        subject = self.request.get('subject')
        content = self.request.get('content')
        author = self.user.name

        if subject and content:
            p = Post(parent=blog_key(), subject=subject, content=content,
                     author=author)
            p.put()
            self.redirect('/blog/%s' % str(p.key().id()))
        else:
            error = "subject and content, please!"
            self.render("newpost.html", subject=subject, content=content,
                        error=error, author=author)


class EditPost(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        if not post:
            return self.redirect('/blog')
        if not self.user or self.user.name != post.author:
            self.redirect('/login')
        else:
            self.render('editpost.html', subject=post.subject,
                        content=post.content, post=post)

    def post(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        if not post:
            return self.redirect('/blog')
        if not self.user or self.user.name != post.author:
            self.redirect('/login')
        else:
            subject = self.request.get('subject')
            content = self.request.get('content')
            if subject and content:
                edited = Post.get_by_id(int(post_id), parent=blog_key())
                edited.subject, edited.content = subject, content
                edited.put()
                return self.redirect('/blog/%s' % str(edited.key().id()))
            else:
                error = "Please fill in the subject and content."
                self.render("edit-form.html", subject=subject, content=content,
                            error=error, post=post)


class LikePost(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            return self.redirect('/blog')

        if self.user:
            if self.user.name == post.author:
                return self.redirect('/blog/%s' % str(post.key().id()))
            else:
                if self.user.name in post.likes:
                    post.likes.remove(self.user.name)
                    post.put()
                    return self.redirect('/blog/%s' % str(post.key().id()))
                else:
                    post.likes.append(self.user.name)
                    post.put()
                    return self.redirect('/blog/%s' % str(post.key().id()))
        else:
            return self.redirect('/blog/%s' % str(post.key().id()))


class DeletePost(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            return self.redirect('/blog')

        if self.user:
            if self.user.name == post.author:
                post.delete()
                # delaying for localhost testing purposes
                # time.sleep(1)
                return self.redirect('/blog')
            else:
                return self.redirect('/login')
        else:
            return self.redirect('/login')


class Comment(db.Model):
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    post = db.ReferenceProperty(Post, collection_name="comments")
    author = db.TextProperty()


class NewComment(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            return self.redirect('/blog')

        if self.user:
            self.render('new-comment.html', post=post)
        else:
            self.redirect('/login')

    def post(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        content = self.request.get("content")

        if self.user and content:
            author = self.user.name
            c = Comment(parent=blog_key(), content=content, post=post,
                        author=author)
            c.put()
            return self.redirect('/blog/%s' % str(post.key().id()))

        else:
            error = "You can't leave a blank comment!"
            self.render("permalink.html", post=post, error=error)


class EditComment(BlogHandler):
    def get(self, comment_id):
        comment = Comment.get_by_id(int(comment_id), parent=blog_key())
        post = comment.post

        if not comment:
            return self.redirect('/blog')
        if not self.user or self.user.name != comment.author:
            self.redirect('/login')
        else:
            self.render('new-comment.html', content=comment.content, post=post)

    def post(self, comment_id):
        comment = Comment.get_by_id(int(comment_id), parent=blog_key())
        post = comment.post

        if not self.user or self.user.name != comment.author:
            self.redirect('/login')
        else:
            content = self.request.get('content')
            if content:
                edited = Comment.get_by_id(int(comment_id), parent=blog_key())
                edited.content = content
                edited.put()
                return self.redirect('/blog/%s' % str(edited.post.key().id()))
            else:
                error = "You can't leave a blank comment!"
                self.render("new-comment.html", content=content, error=error,
                            post=post)


class DeleteComment(BlogHandler):
    def get(self, comment_id):
        comment = Comment.get_by_id(int(comment_id), parent=blog_key())
        post = comment.post

        if not self.user:
            return self.redirect('/login')

        if not comment:
            return self.redirect('/blog')

        if self.user.name == comment.author:
            comment.delete()
            return self.redirect('/blog/%s' % post.key().id())
        elif self.user.name != comment.author:
            return self.redirect('/blog/%s' % post.key().id())

USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")


def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")


def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE = re.compile(r'^[\S]+@[\S]+\.[\S]+$')


def valid_email(email):
    return not email or EMAIL_RE.match(email)


class Signup(BlogHandler):
    def get(self):
        self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username=self.username,
                      email=self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError


class Register(Signup):
    def done(self):
        # make sure the user doesn't already exist
        user = User.by_name(self.username)

        if user:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username=msg)
        else:
            user = User.register(self.username, self.password, self.email)
            user.put()

            self.login(user)
            self.redirect('/blog')


class Login(BlogHandler):
    def get(self):
        if self.user:
            return self.redirect('/blog')
        else:
            self.render('login-form.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        user = User.login(username, password)

        if user:
            self.login(user)
            self.redirect('/blog')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error=msg)


class Logout(BlogHandler):
    def get(self):
        if self.user:
            self.logout()
        self.redirect('/blog')

app = webapp2.WSGIApplication([('/', MainPage),
                               ('/blog/?', BlogFront),
                               ('/blog/([0-9]+)', PostPage),
                               ('/blog/newcomment/([0-9]+)', NewComment),
                               ('/blog/deletecomment/([0-9]+)', DeleteComment),
                               ('/blog/editcomment/([0-9]+)', EditComment),
                               ('/blog/delete/([0-9]+)', DeletePost),
                               ('/blog/edit/([0-9]+)', EditPost),
                               ('/blog/likes/([0-9]+)', LikePost),
                               ('/blog/newpost', NewPost),
                               ('/signup', Register),
                               ('/login', Login),
                               ('/logout', Logout),
                               ],
                              debug=True)
