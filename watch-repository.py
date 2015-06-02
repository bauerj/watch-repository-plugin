# coding=utf8
"""
watch-repository.py - Willie Module
Copyright 2015, bauerj@bauerj.eu
Licensed under the Apache License 2.0

https://github.com/bauerj/watch-repository-plugin/blob/master/LICENSE
"""
from __future__ import unicode_literals
import pprint
import re

from willie.module import commands, interval
from willie.logger import get_logger
from willie import formatting
import requests
import json
import datetime
import dateutil.parser

LOGGER = get_logger(__name__)

INTERVAL = 60 * 2  # seconds between checking for new updates
repo = "facebook/hhvm"


# seems like this method gets called when willie starts
def setup(bot):
    bot.memory['repo_manager'] = RepoManager(bot)
    conn = bot.db.connect()
    c = conn.cursor()

    try:
        c.execute('SELECT * FROM repositories')
        c.execute('SELECT * FROM repos2channels')
    except StandardError:
        bot.memory['repo_manager'].create_table(c)
        conn.commit()
    conn.close()


@commands('repos')
def manage_repos(bot, trigger):
    """Manage repos. For a list of commands, type: .repos help"""
    bot.memory['repo_manager'].manage_repos(bot, trigger)



class RepoManager:
    def __init__(this, bot):
        this.running = True
        this.bot = bot

        # get a list of all methods in this class that start with _repos
        this.actions = sorted(method[7:] for method in dir(this) if method[:7] == '_repos_')

    def manage_repos(this, bot, trigger):
        """Manage repos. Usage: .repos <command>"""
        if not trigger.admin:
            bot.reply("Sorry, you need to be an admin to modify this.")
            return

        text = trigger.group().split()
        if len(text) < 2 or text[1] not in this.actions:
            bot.reply("Usage: .repos <command>")
            bot.reply("Available commands: " + ', '.join(this.actions))
            return

        conn = bot.db.connect()
        # run the function and commit database changes if it returns true
        if getattr(this, '_repos_' + text[1])(bot, trigger, conn.cursor()):
            conn.commit()
        conn.close()

    def _repos_add(this, bot, trigger, c):
        args = trigger.group().split()

        if len(args) < 3 or "/" not in args[2]:
            bot.reply("Usage: .repos add <username/repository>")
            return
        repo = args[2]

        c.execute('''
            SELECT * FROM repositories WHERE name = ?
            ''', [repo])
        if not c.fetchone():
            c.execute('''
                INSERT INTO repositories (name)
                VALUES (?)
                ''', [repo])
            bot.memory['watch-repository'].append(GithubRepo(repo))
            bot.reply("Successfully added the repository. "
                      "Use .repos assign " + repo + " <#channel>. to assign it to a channel."
                                                  "Use .repos enablehook " + repo + " to add a webhook if you can.")
        else:
            bot.reply("Repository " + repo + " is already in the list.")
        return True

    def _repos_remove(this, bot, trigger, c):
        args = trigger.group().split()

        if len(args) < 3 or "/" not in args[2]:
            bot.reply("Usage: .repos remove <username/repository>")
            return
        repo = args[2]

        c.execute('''
            SELECT * FROM repositories WHERE name = ?
            ''', [repo])
        if c.fetchone():
            c.execute('''
                DELETE FROM repositories WHERE name = ?
                ''', [repo])
            bot.memory['watch-repository'] = [i for i in bot.memory['watch-repository'] if i.getName() != repo]
            bot.reply("Successfully removed the repository.")
        else:
            bot.reply("Repository " + repo + " is not in the list.")
        return True

    def _repos_assign(this, bot, trigger, c):
        args = trigger.group().split()
        if len(args) < 4 or "/" not in args[2]:
            bot.reply("Usage: .repos assign <username/repository> <#channel>")
            return
        repo = args[2]
        channel = args[3]
        c.execute('''
            SELECT * FROM repositories WHERE name = ?
            ''', [repo])
        if c.fetchone():
            c.execute('''
                INSERT INTO repos2channels (name, channel)
                VALUES (?, ?)
                ''', (repo, channel))
            bot.reply("Success. I will announce any changes to "+repo+" in "+channel+" (you may need to invite me).")
        else:
            bot.reply("Repository " + repo + " is not in the list. Use .repos add "+repo+" to add it.")
        return True

    def _repos_unassign(this, bot, trigger, c):
        args = trigger.group().split()

        if len(args) < 4 or "/" not in args[2]:
            bot.reply("Usage: .repos unassign <username/repository> <#channel>")
            return
        repo = args[2]
        channel = args[3]

        c.execute('''
            SELECT * FROM repositories WHERE name = ?
            ''', [repo])
        if c.fetchone():
            c.execute('''
                DELETE FROM repos2channels WHERE name = ? AND channel = ?
                ''', [repo, channel])
            bot.reply("Success. I won't announce changes to "+repo+" in "+channel+" any more.")
        else:
            bot.reply("Repository " + repo + " is not in the list. Use .repos add "+repo+" to add it.")
        return True

    def _repos_list(this, bot, trigger, c):
        c.execute("SELECT name, enabled FROM repositories")
        repos = c.fetchall()
        list = ""
        for (name, enabled) in repos:
            list += name
            if not enabled:
                list += "(inactive)"
            list += ", "
        list.rstrip(", ")
        bot.reply("I know the following repositories: " + list)

    def _repos_fetch(this, bot, trigger, c):
        """Fetch all repositories that have no webhook"""
        read_repo(bot)

    def create_table(this, c):
        c.execute('''CREATE TABLE IF NOT EXISTS repositories (
            name TEXT,
            push BOOL DEFAULT 0,
            push_token TEXT,
            enabled BOOL DEFAULT 1,
            PRIMARY KEY (name)
            )''')
        c.execute('''CREATE TABLE IF NOT EXISTS repos2channels (
            name TEXT,
            channel TEXT,
            PRIMARY KEY (name, channel)
            )''')

@interval(INTERVAL)
def read_repo(bot):
    if 'watch-repository' not in bot.memory:
        bot.memory['watch-repository'] = []
        conn = bot.db.connect()
        c = conn.cursor()
        c.execute("SELECT name FROM repositories WHERE push = 0")
        repos = c.fetchall()
        for i in repos:
            bot.memory['watch-repository'].append(GithubRepo(i[0]))
    for w in bot.memory['watch-repository']:
        for type in {"commits", "issues"}:
            all = w.getNew(type)
            for item in all:
                for channel in getChannelsFor(bot, w.getName()):
                    bot.msg(channel, announce(type, item, w.getName()))

def getChannelsFor(bot, repo):
    conn = bot.db.connect()
    c = conn.cursor()
    c.execute("SELECT channel FROM repos2channels WHERE name = ?", [repo])
    return [i[0] for i in c.fetchall()]

def announce(type, o, repo):
    name = {'commits': 'Commit', 'issues': 'Bug-Report', 'pull': 'Pull-Request'}
    if "pull_request" in o:
        type = "pull"
    msg = "Neuer " + name[type] + " in " + repo + " von "
    msg += (o.get("user", {}).get("login", None) or o.get("commit", {}).get("author", {}).get("name", None) or "???")
    msg += ": " + formatting.color((o.get("title", None) or o.get("commit", {}).get("message", None) or "?"), "white", "black")
    msg += "( " + o["html_url"] + " )"
    return msg


class GithubRepo:
    def __init__(this, name):
        LOGGER.debug("initialized GithubRepo-object")
        this.name = name
        this.etags = {}
        this.last = {
            'commits': this.getISOTime(),
            'pulls': this.getISOTime(),
            'issues': this.getISOTime()
        }

    def fetch(this, url):
        headers = {'User-Agent': 'https://github.com/bauerj/watch-repository-plugin'}
        if url in this.etags:
            headers['If-None-Match'] = this.etags[url]
        r = requests.get(url, headers=headers)
        if 'ETag' in r.headers:
            this.etags[url] = r.headers['ETag']
        print("fetched " + url + ", status: %i" % r.status_code)
        if "X-RateLimit-Remaining" in r.headers:
            print("RateLimit Remaining: " + r.headers["X-RateLimit-Remaining"])
        if r.status_code == 304:
            return {}
        return json.loads(r.text or r.content)

    def getNew(this, what):
        response = this.fetch("https://api.github.com/repos/" + this.name + "/" + what)

        # use list comprehension to filter
        response = [i for i in response if this.toTimestamp(this.getDate(i)) > this.toTimestamp(this.last[what])]

        if len(response) > 0:
            this.last[what] = this.getDate(response[0])
        return response

    # ISO8601 or something like that
    def getISOTime(this):
        return datetime.datetime.utcnow().isoformat() + "Z"

    def toTimestamp(this, item):
        return dateutil.parser.parse(item)

    def getDate(this, i):
        return i.get("commit", {}).get("committer", {}).get("date", None) or i.get("created_at", None) or this.getISOTime()

    def getName(this):
        return this.name
