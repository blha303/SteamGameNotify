from twisted.internet import reactor, task, defer, protocol
from twisted.python import log
from twisted.words.protocols import irc
from twisted.application import internet, service

import yaml, sys, datetime, requests, json, steamapi, itertools

with open('config.yml') as f:
    config = yaml.load(f.read())
HOST, PORT = config['host'], config['port']
KEY = config["steam_api_key"]
CLIENT = steamapi.core.APIConnection(api_key=KEY)

users = []

def say(info, msg):
    info["msg"](info["channel"], msg)
    log.msg("{}: {}".format(info["channel"], msg))

def save():
    global users
    try:
        with open("users.json", "w") as f:
            json.dump(users, f)
        return True
    except:
        raise
        return False

def game_name_from_id(user, id):
    try:
        return [a.name.encode("utf-8") for a in user.games if a.id == id][0]
    except:
        raise
        return "<{}>".format(id)

def check_user_already_added(uid):
    global users
    if any(uid in a for a in users):
        return [a for a in users if a[0] == uid][0]
    else:
        return False

def u_steamhelp(info, msg):
    """!steamhelp - List commands"""
    info["channel"] = info["nick"]
    say(info, "Commands: {}".format(", ".join([globals()[f].__doc__ for f in globals() if f[:2] == "u_"])))

def u_sadduser(info, msg):
    """!sadduser <user...> - Adds user(s) to update list"""
    global users
    if not msg:
        say(info, globals()[sys._getframe().f_code.co_name].__doc__)
        return
    newusers = msg.split(" ")
    for u in newusers:
        if not u.isdigit():
            say(info, "Retrieving user ID for {} (next time, please provide the numeric user ID. i.e 76561197994805502)".format(u))
            try:
                u = steamapi.user.SteamUser(userurl=u).id
            except steamapi.errors.UserNotFoundError, e:
                say(info, "Error adding {}: {}".format(u, e))
                continue
        if check_user_already_added(u):
            say(info, "{} has already been added!".format(u))
            continue
        try:
            user = steamapi.user.SteamUser(int(u))
        except steamapi.errors.UserNotFoundError, e:
            say(info, "Error adding {}: {}".format(u, e))
            continue
        users.append([u, [_.id for _ in user.games]]) # list: [user_id, game_id_set]
        say(info, "{} added!".format(user.name))
    save()

def u_sdeluser(info, msg):
    """!sdeluser <user...> - Removes user(s) from update list"""
    global users
    if not msg:
        say(info, globals()[sys._getframe().f_code.co_name].__doc__)
        return
    newusers = msg.split(" ")
    for u in newusers:
        if not u.isdigit():
            say(info, "Retrieving user ID for {} (next time, please provide the numeric user ID. i.e 76561197994805502)".format(u))
            try:
                u = steamapi.user.SteamUser(userurl=u).id
            except steamapi.errors.UserNotFoundError, e:
                say(info, "Error removing {}: {}".format(u, e))
                continue
        _ = check_user_already_added(u)
        if _:
            try:
                users.remove(_)
                say(info, "Removed {}.".format(u))
            except:
                say(info, "Error removing {}.")
                raise
        else:
            say(info, "User has not been added.")
    save()

class SteamBuyProtocol(irc.IRCClient):
    nickname = config['nick']
    password = config['password'] if 'password' in config else None
    username = config['nick']
    versionName = "SteamBuy"
    versionNum = "v0.0.1"
    realname = "https://github.com/blha303/SteamGameNotify"
    loopcall = None
    global users
    try:
        with open("users.json") as f:
            users = json.load(f)
    except:
        with open("users.json", "w") as f:
            json.dump(users, f)

    def signedOn(self):
        if "nickserv" in config:
            self.msg("NickServ", "identify {}".format(config["nickserv"]))
        for channel in self.factory.channels:
            self.join(channel)
        self.loopcall = task.LoopingCall(self.updateGames)
        self.loopcall.start(60.0)

    def updateGames(self):
        global users
        log.msg("Updating games for {} user{}".format(len(users), "s" if len(users) != 1 else ""))
        for u,ids in users:
            try:
                user = steamapi.user.SteamUser(u)
                newids = [_.id for _ in user.games]
            except:
                log.err("Unable to get current list of games for {}".format(u))
                continue
            changes = list(set(newids) - set(ids))
            if changes:
                users.remove([u,ids])
                users.append([u,newids])
                log.msg("Update to {}: {}".format(u, ",".join(str(_) for _ in changes)))
                for channel in config["channels"]:
                    self.msg(channel,
                             "{} has added {}! \x02{}".format(user.name,
                                                          "{} new games".format(len(changes)) if len(changes) > 1 else "a new game",
                                                          "\x0f, \x02".join([game_name_from_id(user, id) for id in changes])
                                                         ))
            else:
                log.msg("No update to {}".format(u))
        save()

    def privmsg(self, user, channel, message):
        if not save():
            self.msg(channel, "Unable to save user list! Please check")
        nick, _, host = user.partition('!')
        if not channel in self.factory.channels:
            return
#        log.msg("{} <{}> {}".format(channel, nick, message))
        if message[0][0] == "!":
            message = message.strip().split(" ")
            msginfo = {'nick': nick, 'host': host, 'channel': channel, 'message': message, 'notice': self.notice, 'msg': self.msg}
            if channel == self.nickname:
                channel = nick
            try:
                log.msg("{} used {}".format(nick, " ".join(message)))
                globals()["u_" + message[0][1:]](msginfo, " ".join(message[1:]) if len(message) > 1 else "")
            except KeyError:
                log.msg("Command not found, probably for another bot")

class SteamBuyFactory(protocol.ReconnectingClientFactory):
    protocol = SteamBuyProtocol
    channels = config["channels"]

if __name__ == '__main__':
    reactor.connectTCP(HOST, PORT, SteamBuyFactory())
    log.startLogging(sys.stdout)
    reactor.run()

elif __name__ == '__builtin__':
    application = service.Application('SteamBuy')
    ircService = internet.TCPClient(HOST, PORT, SteamBuyFactory())
    ircService.setServiceParent(application)
