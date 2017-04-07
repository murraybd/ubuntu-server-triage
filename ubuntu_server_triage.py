#!/usr/bin/env python3
"""
Output Ubuntu Server Launchpad bugs that for triage. Script accepts either
a single date or inclusive range to find bugs.

Copyright 2016 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""
import argparse
from datetime import datetime, timedelta
import logging
import os
import sys
import webbrowser

from launchpadlib.launchpad import Launchpad


LOG_LEVEL = logging.INFO


class Task:
    '''Our representation of a Launchpad task.

    This encapsulates a launchpadlib Task object, caches some queries,
    stores some other properties (eg. the team-"subscribed"-ness) as needed
    by callers, and presents a bunch of derived properties. All Task property
    specific handling is encapsulated here.
    '''
    LONG_URL_ROOT = 'https://bugs.launchpad.net/bugs/'
    SHORTLINK_ROOT = 'LP: #'
    BUG_NUMBER_LENGTH = 7

    def __init__(self):
        self._cache = {}
        self.subscribed = None  # whether the team is subscribed to the bug

    @staticmethod
    def create_from_launchpadlib_object(obj, **kwargs):
        self = Task()
        self.obj = obj
        for k, v in kwargs.items():
            setattr(self, k, v)
        return self

    @property
    def url(self):
        '''The user-facing URL of the task'''
        return self.LONG_URL_ROOT + self.number

    @property
    def shortlink(self):
        '''The user-facing "shortlink" that gnome-terminal will autolink'''
        return self.SHORTLINK_ROOT + self.number

    @property
    def number(self):
        '''The bug number as a string'''
        try:
            return self._cache['number']
        except KeyError:
            self._cache['number'] = self.title.split(' ')[1].replace('#', '')
            return self._cache['number']

    @property
    def src(self):
        '''The source package name'''
        try:
            return self._cache['src']
        except KeyError:
            self._cache['src'] = self.title.split(' ')[3]
            return self._cache['src']

    @property
    def title(self):
        '''The "title" as returned by launchpadlib'''
        try:
            return self._cache['title']
        except KeyError:
            self._cache['title'] = self.obj.title
            return self._cache['title']

    @property
    def status(self):
        '''The "status" as returned by launchpadlib'''
        try:
            return self._cache['status']
        except KeyError:
            self._cache['status'] = self.obj.status
            return self._cache['status']

    @property
    def short_title(self):
        '''Just the bug summary'''
        try:
            return self._cache['short_title']
        except KeyError:
            short_title = ' '.join(self.title.split(' ')[5:]).replace('"', '')
            self._cache['short_title'] = short_title
            return self._cache['short_title']

    def compose_pretty(self, shortlinks=True):
        '''Compose a printable line of relevant information'''
        if shortlinks:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.SHORTLINK_ROOT)) +
                's'
            )
            bug_url = format_string % self.shortlink
        else:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.LONG_URL_ROOT)) +
                's'
            )
            bug_url = format_string % self.url

        return '%s - %-16s %-16s - %s' % (
            bug_url,
            ('%s(%s)' % (('*' if self.subscribed else ''), self.status)),
            ('[%s]' % self.src), self.short_title
        )


def connect_launchpad():
    """
    Using the launchpad module connect to launchpad.

    Will connect you to the Launchpad website the first time you run
    this to autorize your system to connect.
    """
    return Launchpad.login_with('ubuntu-server-triage.py', 'production')


def check_dates(start, end=None, nodatefilter=False):
    """
    Validate dates are setup correctly so we can print the range
    and then be inclusive in dates.
    """
    # if start date is not set we search all bugs of a LP user/team
    if not start:
        if nodatefilter:
            logging.info('Searching all bugs, no date filter')
            return datetime.min, datetime.now()

        logging.info('No date set, auto-search yesterday/weekend for the '
                     'most common triage.')
        logging.info('Please specify -a if you really '
                     'want to search without any date filter')
        yesterday = datetime.now().date() - timedelta(days=1)
        if yesterday.weekday() != 6:
            start = yesterday.strftime('%Y-%m-%d')
        else:
            # include weekend if yesterday was a sunday
            start = (yesterday - timedelta(days=2)).strftime('%Y-%m-%d')
            end = yesterday.strftime('%Y-%m-%d')

    # If end date is not set set it to start so we can
    # properly show the inclusive list of dates.
    if not end:
        end = start

    logging.info('%s to %s (inclusive)', start, end)

    # Always add one to end date to make the dates inclusive
    end = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    end = end.strftime('%Y-%m-%d')

    logging.debug('Searching for %s and %s', start, end)

    return start, end


def print_bugs(tasks, open_in_browser=False, shortlinks=True):
    """
    Prints the tasks in a clean-ish format.
    """

    for task in tasks:
        logging.info(task.compose_pretty(shortlinks=shortlinks))
        if open_in_browser:
            webbrowser.open(task.url)


def modified_bugs(start_date, end_date, lpname, bugsubscriber):
    """
    Returns a list of bugs modified between dates.
    """
    # Distribution List: https://launchpad.net/distros
    # API Doc: https://launchpad.net/+apidoc/1.0.html
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]

    if bugsubscriber:
        # direct subscriber
        bugs_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, bug_subscriber=team
            )}
        bugs_since_end = {
            task.self_link: task for task in project.searchTasks(
                modified_since=end_date, bug_subscriber=team
            )}

        # N/A for direct subscribers
        already_sub_since_start = {}

    else:
        # structural_subscriber sans already subscribed
        bugs_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, structural_subscriber=team
            )}
        bugs_since_end = {
            task.self_link: task for task in project.searchTasks(
                modified_since=end_date, structural_subscriber=team
            )}
        already_sub_since_start = {
            task.self_link: task for task in project.searchTasks(
                modified_since=start_date, structural_subscriber=team,
                bug_subscriber=team
            )}

    bugs_in_range = {
        link: task for link, task in bugs_since_start.items()
        if link not in bugs_since_end
    }

    bugs = {
        Task.create_from_launchpadlib_object(
            task,
            subscribed=(link in already_sub_since_start),
        )
        for link, task in bugs_in_range.items()
    }

    return bugs


def create_bug_list(start_date, end_date, lpname, bugsubscriber, nodatefilter):
    """
    Subtracts all bugs modified after specified start and end dates.

    This provides the list of bugs between two dates as Launchpad does
    not appear to have a specific function for searching for a range.
    """
    logging.info('Please be patient, this can take a few minutes...')
    start_date, end_date = check_dates(start_date, end_date, nodatefilter)

    tasks = modified_bugs(start_date, end_date, lpname, bugsubscriber)

    logging.info('Found %s bugs', len(tasks))
    logging.info('---')

    return tasks


def report_current_backlog(lpname):
    """
    Reports how much bugs the team is currently subscribed to.

    This value is usually needed to track how the backlog is growing/shrinking.
    """
    launchpad = connect_launchpad()
    project = launchpad.distributions['Ubuntu']
    team = launchpad.people[lpname]
    sub_bugs = project.searchTasks(bug_subscriber=team)
    logging.info('Team %s currently subscribed to %d bugs',
                 lpname, len(sub_bugs))
    logging.info('---')


def main(start=None, end=None, open_in_browser=False, lpname="ubuntu-server",
         bugsubscriber=False, nodatefilter=False, shortlinks=True):
    """
    Connect to Launchpad, get range of bugs, print 'em.
    """
    logging.basicConfig(stream=sys.stdout, format='%(message)s',
                        level=LOG_LEVEL)

    connect_launchpad()
    logging.info('Ubuntu Server Bug List')
    report_current_backlog(lpname)
    bugs = create_bug_list(start, end, lpname, bugsubscriber, nodatefilter)
    print_bugs(bugs, open_in_browser, shortlinks)


if __name__ == '__main__':
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument('start_date',
                        nargs='?',
                        help='date to start finding bugs ' +
                        '(e.g. 2016-07-15)')
    PARSER.add_argument('end_date',
                        nargs='?',
                        help='date to end finding bugs (inclusive) ' +
                        '(e.g. 2016-07-31)')
    PARSER.add_argument('-d', '--debug', action='store_true',
                        help='debug output')
    PARSER.add_argument('-o', '--open', action='store_true',
                        help='open in web browser')
    PARSER.add_argument('-a', '--nodatefilter', action='store_true',
                        help='show all (no date restriction)')
    PARSER.add_argument('-n', '--lpname', default='ubuntu-server',
                        help='specify the launchpad name to search for')
    PARSER.add_argument('-b', '--bugsubscriber', action='store_true',
                        help=('filter name as bug subscriber (default would '
                              'be structural subscriber'))
    PARSER.add_argument('--fullurls', default=False, action='store_true',
                        help='show full URLs instead of shortcuts')

    ARGS = PARSER.parse_args()

    if ARGS.debug:
        LOG_LEVEL = logging.DEBUG

    main(ARGS.start_date, ARGS.end_date, ARGS.open, ARGS.lpname,
         ARGS.bugsubscriber, ARGS.nodatefilter, not ARGS.fullurls)
