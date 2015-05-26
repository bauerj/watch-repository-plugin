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

LOGGER = get_logger(__name__)

INTERVAL = 60 * 1  # seconds between checking for new updates
repo = "facebook/hhvm"
channel = "#jreuab"


@interval(INTERVAL)
def read_repo(bot):
    if (not 'watch-repository' in bot.memory):
        bot.memory['watch-repository'] = GithubRepo(repo)
    w = bot.memory['watch-repository']
    commits = w.getNew("commits")
    for i in commits:
        msg = "Neuer Commit in " + repo + " von "
        msg += i["committer"]["name"] + ": "
        msg += i["message"]
        msg += "(" + i["html_url"] + ")"
        bot.msg(channel, msg)

    issues = w.getNew("issues")
    for i in issues:
        msg = "Neuer Issue in " + repo + " von "
        msg += i["user"]["login"] + ": "
        msg += i["title"]
        msg += "(" + i["html_url"] + ")"
        bot.msg(channel, msg)


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
        if what in this.last:
            response = this.fetch("https://api.github.com/repos/" + this.name + "/" + what + "?since=" + this.last[what])
        else:
            response = this.fetch("https://api.github.com/repos/" + this.name + "/" + what)
        if what == 'commits' and len(response) > 0 and hasattr(response[0],
                                                               'committer' and hasattr(response[0].commiter, 'date')):
            this.last[what] = response[0].committer.date
        elif len(response) > 0 and hasattr(response[0], 'created_at'):
            this.last[what] = response[0].created_at
        else:
            this.last[what] = this.getISOTime()
        return response

    def getISOTime(this):
        return datetime.datetime.utcnow().isoformat() + "Z"
