#!/usr/bin/env python3
import re
from pathlib import Path

import discord
import json
from discord.ext import commands
import yt_dlp
import urllib
import asyncio
import threading
import os
import shutil
import sys
import subprocess as sp
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PREFIX = os.getenv('BOT_PREFIX', '.')
YTDL_FORMAT = os.getenv('YTDL_FORMAT', 'bestaudio')
PRINT_STACK_TRACE = os.getenv('PRINT_STACK_TRACE', '1').lower() in ('true', 't', '1')
BOT_REPORT_COMMAND_NOT_FOUND = os.getenv('BOT_REPORT_COMMAND_NOT_FOUND', '1').lower() in ('true', 't', '1')
BOT_REPORT_DL_ERROR = os.getenv('BOT_REPORT_DL_ERROR', '0').lower() in ('true', 't', '1')
try:
    COLOR = int(os.getenv('BOT_COLOR', 'ff0000'), 16)
except ValueError:
    print('the BOT_COLOR in .env is not a valid hex color')
    print('using default color ff0000')
    COLOR = 0xff0000

bot = commands.Bot(command_prefix=PREFIX, intents=discord.Intents(voice_states=True, guilds=True, guild_messages=True, message_content=True))
queues = {} # {server_id: 'queue': [(vid_file, info), ...], 'loop': bool}
#white_list = [351457752108892172, 209907269050040320, 201098387058196481, 207987195707916288]

with open('users/users.json') as json_data:
    data = json.load(json_data)
    json_data.close()
super_admin = set(data['super_admin'])
admin = set(data['admin'])
whitelist = set(data['whitelist'])
blacklist = set(data['blacklist'])
print(f'super admin: {super_admin}')
print(f'admin: {admin}')
print(f'loaded {len(whitelist)} whitelisted users and {len(blacklist)} blacklisted users')
print(f'whitelist: {whitelist}\nblacklist: {blacklist}')

def main():
    if TOKEN is None:
        return ("no token provided. Please create a .env file containing the token.\n"
                "for more information view the README.md")
    try: 
        bot.run(TOKEN)
    except discord.PrivilegedIntentsRequired as error:
        return error
    
@bot.command(name='admin', aliases=['a'])
async def addadmin(ctx: commands.Context, *args):
    if ctx.author.id not in super_admin:
        await ctx.send('you are not a super admin')
        return
    
    if len(args) == 0:
        await ctx.send(f'admin: {admin}')
        return
    
    for user in args:
        try:
            admin.add(int(user))
            await ctx.send(f'added {user} to admin')
        except Exception:
            await ctx.send(f'failed to add {user} to admin')
    write_json()

@bot.command(name='unadmin', aliases=['ua'])
async def unadmin(ctx: commands.Context, *args):
    if ctx.author.id not in super_admin:
        await ctx.send('you are not a super admin')
        return
    
    if len(args) == 0:
        await ctx.send('you have to provide a user id to unadmin')
        return
    else:
        for user in args:
            try:
                if int(user) in admin:
                    admin.remove(int(user))
                    await ctx.send(f'removed {user} from admin')
                else:
                    await ctx.send(f'{user} is not a admin')
            except Exception:
                await ctx.send(f'failed to remove {user} from admin')
    write_json()

@bot.command(name='ban', aliases=['b'])
async def ban(ctx: commands.Context, *args):
    if ctx.author.id not in admin:
        await ctx.send('you are not an admin')
        return
    
    if len(args) == 0:
        await ctx.send(f'blacklist: {blacklist}')
        return
    
    for user in args:
        try:
            blacklist.add(int(user))
            await ctx.send(f'added {user} to blacklist')
        except Exception:
            await ctx.send(f'failed to add {user} to blacklist')
    write_json()

@bot.command(name='unban', aliases=['ub'])
async def unban(ctx: commands.Context, *args):
    if ctx.author.id not in admin:
        await ctx.send('you are not an admin')
        return
    
    if len(args) == 0:
        await ctx.send('you have to provide a user id to unban')
        return
    if len(args) == 1 and args[0] == 'all':
        blacklist.clear()
        await ctx.send('cleared blacklist')
    else:
        for user in args:
            try:
                if int(user) in blacklist:
                    blacklist.remove(int(user))
                    await ctx.send(f'removed {user} from blacklist')
                else:
                    await ctx.send(f'{user} is not in blacklist')
            except Exception:
                await ctx.send(f'failed to remove {user} from blacklist')
    write_json()
        

def write_json():
    with open('users/users.json', 'w') as json_data:
        data['super_admin'] = list(super_admin)
        data['admin'] = list(admin)
        data['whitelist'] = list(whitelist)
        data['blacklist'] = list(blacklist)
        json.dump(data, json_data)
        json_data.close()

@bot.command(name='queue', aliases=['q'])
async def queue(ctx: commands.Context, *args):
    try: queue = queues[ctx.guild.id]['queue']
    except KeyError: queue = None
    if queue == None:
        await ctx.send('the bot isn\'t playing anything')
    else:
        title_str = lambda val: '‣ %s\n\n' % val[1] if val[0] == 0 else '**%2d:** %s\n' % val
        queue_str = ''.join(map(title_str, enumerate([i[1]["title"] for i in queue])))
        embedVar = discord.Embed(color=COLOR)
        embedVar.add_field(name='Now playing:', value=queue_str)
        await ctx.send(embed=embedVar)
    if not await sense_checks(ctx):
        return

@bot.command(name='skip', aliases=['s'])
async def skip(ctx: commands.Context, *args):
    try: queue_length = len(queues[ctx.guild.id]['queue'])
    except KeyError: queue_length = 0
    if queue_length <= 0:
        await ctx.send('the bot isn\'t playing anything')
    if not await sense_checks(ctx):
        return

    try: n_skips = int(args[0])
    except IndexError:
        n_skips = 1
    except ValueError:
        if args[0] == 'all': n_skips = queue_length
        else: n_skips = 1
    if n_skips == 1:
        message = 'skipping track'
    elif n_skips < queue_length:
        message = f'skipping `{n_skips}` of `{queue_length}` tracks'
    else:
        message = 'skipping all tracks'
        n_skips = queue_length
    await ctx.send(message)

    voice_client = get_voice_client_from_channel_id(ctx.author.voice.channel.id)
    for _ in range(n_skips - 1):
        queues[ctx.guild.id]['queue'].pop(0)
    voice_client.stop()

@bot.command(name='play', aliases=['p'])
async def play(ctx: commands.Context, *args):
    voice_state = ctx.author.voice
    if not await sense_checks(ctx, voice_state=voice_state):
        return

    query = ' '.join(args)
    # this is how it's determined if the url is valid (i.e. whether to search or not) under the hood of yt-dlp
    will_need_search = not urllib.parse.urlparse(query).scheme

    server_id = ctx.guild.id

    # source address as 0.0.0.0 to force ipv4 because ipv6 breaks it for some reason
    # this is equivalent to --force-ipv4 (line 312 of https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/options.py)
    await ctx.send(f'looking for `{query}`...')
    with yt_dlp.YoutubeDL({'format': YTDL_FORMAT,
                           'source_address': '0.0.0.0',
                           'default_search': 'ytsearch',
                           'outtmpl': '%(id)s.%(ext)s',
                           'noplaylist': True,
                           'allow_playlist_files': False,
                           'cookiefile': "./cookies.firefox-private.txt",
                           # 'progress_hooks': [lambda info, ctx=ctx: video_progress_hook(ctx, info)],
                           # 'match_filter': lambda info, incomplete, will_need_search=will_need_search, ctx=ctx: start_hook(ctx, info, incomplete, will_need_search),
                           'paths': {'home': f'./dl/{server_id}'}}) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
        except yt_dlp.utils.DownloadError as err:
            await notify_about_failure(ctx, err)
            return

        if 'entries' in info:
            info = info['entries'][0]
        # send link if it was a search, otherwise send title as sending link again would clutter chat with previews
        await ctx.send('queuing up ' + (f'https://youtu.be/{info["id"]}' if will_need_search else f'`{info["title"]}`'))
        # try:
        #     ydl.download([query])
        # except yt_dlp.utils.DownloadError as err:
        #     await notify_about_failure(ctx, err)
        #     return
        path = info['url']
        try:
            queues[server_id]['queue'].append(path)
            print("Queue size: " + str(len(queues[server_id]['queue'])))
        except KeyError: # first in queue
            queues[server_id] = {'queue': [path], 'loop': False}
            print("Queue size: " + str(len(queues[server_id]['queue'])))
            try: connection = await voice_state.channel.connect()
            except discord.ClientException: connection = get_voice_client_from_channel_id(voice_state.channel.id)
            # connection.play(discord.FFmpegOpusAudio(path), after=lambda error=None, connection=connection, server_id=server_id:
            #                                                  after_track(error, connection, server_id))
            ffmpeg_options = {'options': '-vn'}
            connection.play(discord.FFmpegOpusAudio(path, **ffmpeg_options), after=lambda error=None, connection=connection, server_id=server_id:
                                                    after_track(error, connection, server_id))

@bot.command('loop', aliases=['l'])
async def loop(ctx: commands.Context, *args):
    if not await sense_checks(ctx):
        return
    try:
        loop = queues[ctx.guild.id]['loop']
    except KeyError:
        await ctx.send('the bot isn\'t playing anything')
        return
    queues[ctx.guild.id]['loop'] = not loop

    await ctx.send('looping is now ' + ('on' if not loop else 'off'))

def get_voice_client_from_channel_id(channel_id: int):
    for voice_client in bot.voice_clients:
        if voice_client.channel.id == channel_id:
            return voice_client
           
def after_track(error, connection, server_id):
    if error is not None:
        print(error)
    try:
        last_video_path = queues[server_id]['queue'][0]
        if not queues[server_id]['loop']:         
            # os.remove(last_video_path)
            queues[server_id]['queue'].pop(0)
    except KeyError: return # probably got disconnected
    except error:
        print(error)
    if last_video_path not in [i[0] for i in queues[server_id]['queue']]: # check that the same video isn't queued multiple times
        try: 
            pass
            # os.remove(last_video_path)
        except FileNotFoundError: pass
    try:
        print("playing next track") 
        connection.play(discord.FFmpegOpusAudio(queues[server_id]['queue'][0]), after=lambda error=None, connection=connection, server_id=server_id:
                                                                          after_track(error, connection, server_id))
    except IndexError: # that was the last item in queue
        queues.pop(server_id) # directory will be deleted on disconnect
        asyncio.run_coroutine_threadsafe(safe_disconnect(connection), bot.loop).result()

        

async def safe_disconnect(connection):
    if not connection.is_playing():
        await connection.disconnect()


async def auth_check(ctx: commands.Context) -> bool:
    if whitelist and not (ctx.author.id in whitelist):
        await ctx.send('suck my dick. make ur own bot')
        return False
    if ctx.author.id in blacklist:
        await ctx.send('fuck you bilal')
        return False
    return True
    
async def sense_checks(ctx: commands.Context, voice_state=None) -> bool:
    auth_check_result = await auth_check(ctx)
    if not auth_check_result: return False
    if voice_state is None: voice_state = ctx.author.voice
    if voice_state is None:
        await ctx.send('you have to be in a voice channel to use this command')
        return False

    if bot.user.id not in [member.id for member in ctx.author.voice.channel.members] and ctx.guild.id in queues.keys():
        await ctx.send('you have to be in the same voice channel as the bot to use this command')
        return False
    return True

@bot.event
async def on_voice_state_update(member: discord.User, before: discord.VoiceState, after: discord.VoiceState):
    if member != bot.user:
        return
    if before.channel is None and after.channel is not None: # joined vc
        return
    if before.channel is not None and after.channel is None: # disconnected from vc
        # clean up
        server_id = before.channel.guild.id
        try: queues.pop(server_id)
        except KeyError: pass
        try: #shutil.rmtree(f'./dl/{server_id}/')
            pass
        except FileNotFoundError: pass

@bot.event
async def on_command_error(ctx: discord.ext.commands.Context, err: discord.ext.commands.CommandError):
    # now we can handle command errors
    if isinstance(err, discord.ext.commands.errors.CommandNotFound):
        if BOT_REPORT_COMMAND_NOT_FOUND:
            await ctx.send("command not recognized. To see available commands type {}help".format(PREFIX))
        return

    # we ran out of handlable exceptions, re-start. type_ and value are None for these
    sys.stderr.write(f'unhandled command error raised, {err=}')
    sys.stderr.flush()
    sp.run(['./restart'])

@bot.event
async def on_ready():
    print(f'logged in successfully as {bot.user.name}')
async def notify_about_failure(ctx: commands.Context, err: yt_dlp.utils.DownloadError):
    if BOT_REPORT_DL_ERROR:
        # remove shell colors for discord message
        sanitized = re.compile(r'\x1b[^m]*m').sub('', err.msg).strip()
        if sanitized[0:5].lower() == "error":
            # if message starts with error, strip it to avoid being redundant
            sanitized = sanitized[5:].strip(" :")
        await ctx.send('failed to download due to error: {}'.format(sanitized))
    else:
        await ctx.send('sorry, failed to download this video')
    return

if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemError as error:#
        if PRINT_STACK_TRACE:
            raise
        else:
            print(error)
