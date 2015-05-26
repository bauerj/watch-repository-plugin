# coding=utf8
"""
watch-repository.py - Willie Module
Copyright 2015, bauerj@bauerj.eu
Licensed under the Apache License 2.0

https://github.com/bauerj/watch-repository-plugin/blob/master/LICENSE
"""
from __future__ import unicode_literals

from willie.module import interval
from willie.logger import get_logger
import requests
import json
import datetime
import dateutil.parser

LOGGER = get_logger(__name__)

INTERVAL = 60 * 5  # seconds between checking for new updates
repo = "facebook/hhvm"
channel = "#jreuab"


class RepoManager:
    def _repo_fetch(this, bot, c):
        """Fetch all repositories that have no webhook immediately"""
        this.read_repo(bot)

    @interval(INTERVAL)
    def read_repo(this, bot):
        if 'watch-repository' not in bot.memory:
            bot.memory['watch-repository'] = GithubRepo(repo)
        w = bot.memory['watch-repository']
        for type in {"commits", "pulls", "issues"}:
            all = w.getNew(type)
            for i in all:
                bot.msg(channel, this.announce(type, i))

    def announce(this, type, o):
        name = {'commits': 'Commit', 'issues': 'Bug-Report', 'pulls': 'Pull-Request'}
        msg = "Neuer " + name[type] + " in " + repo + " von "
        msg += o["user"]["login"] or o["committer"]["name"] or "???"
        msg += ": " + o["title"] or o["message"]
        msg += "(" + o["html_url"] + ")"
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

    def getDate(this, item):
        if hasattr(item, 'committer' and hasattr(item.commiter, 'date')):
            return item.committer.date
        elif hasattr(item, 'created_at'):
            return item.created_at
        else:
            return this.getISOTime()
