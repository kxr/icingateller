#!/usr/bin/env python3

from telegram.ext import Job, Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
import logging, os, pickle, glob, smtplib, uuid
from email.mime.text import MIMEText
from secrets import BOTTOKEN, AD, BASEDN, BINDDN, BINDPW

# Enable logging
logging.basicConfig( format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
					level=logging.INFO )
logger = logging.getLogger( __name__ )

REGDIR = "/opt/icingateller/registry/"
PASSWORD = "HBMsU"
ICINGAALERTS = "/opt/icingateller/alerts/"
ALERTCHANNELS = { 'EI', 'ELS', 'EES', 'BAN', 'TST' }
SMTPSERVER = "192.168.2.57"
SMTPFROM = "icinga-telegram@hbmsu.ac.ae"
EMAILDOMAIN = 'hbmsu.ac.ae'


# Authorized Chat-Channel-Cache aka CCC
# A dictionary of authorized chats and
# the  channels the chat is subscribed to.
# So we don't have to read from the disk,
# every time there is a new alert.
CCC = {	'auth': {},
	'unauth': {} }
def gen_chat_channels_cache():
	global CCC
	CCC = {	'auth': {},
		'unauth': {} }
	# Loop on all chats
	for chat in glob.glob( REGDIR + '/*' ):
		chat_id = os.path.basename( chat )
		users = {	'auth': {},
				'unauth': {} }
		channels = set()
		# Go through each file
		for cfiles in glob.glob( chat + '/*' ):
			bfile = os.path.basename( cfiles )
			if bfile.startswith( 'chan-' ):
				channels.add( bfile[5:] )
			else:
				with open( chat + '/' + bfile, 'rb' ) as f:
					userdict = pickle.load(f)
				if 'authorized' in userdict and userdict['authorized'] == True:
					users['auth'][userdict['id']] = userdict
				else:
					users['unauth'][userdict['id']] = userdict
		if len( users['auth'] ) > 0:
			CCC['auth'][chat_id] = {}
			CCC['auth'][chat_id]['users'] = users
			CCC['auth'][chat_id]['channels'] = channels
		else:
			CCC['unauth'][chat_id] = {}
			CCC['unauth'][chat_id]['users'] = users
			CCC['unauth'][chat_id]['channels'] = channels

# Icinga polling and alerting function
def icinga_alert_job( bot, job ):

	# Loop through all alerts
	for alertf in glob.glob( ICINGAALERTS + '/*.alert' ):
		# Read the alert
		with open( alertf, 'r' ) as f:
			alertmsg = f.read()
		# Get the alert groups
		alertgroups = set( os.path.basename( alertf ).split('-')[0].split(';') )
		# Magic
		chatstoalert = [ chat for chat, value in CCC['auth'].items() if bool( set(value['channels']) & set(alertgroups)) ]
		for c in chatstoalert:
			bot.send_message( c, alertmsg )
		os.rename( alertf, ICINGAALERTS + '/done/' + os.path.basename( alertf ) )

# Get user info
def getUserInfo( user ):
	import ldap
	l = ldap.initialize( AD )
	l.protocol_version = 3
	l.set_option(ldap.OPT_REFERRALS, 0)
	l.simple_bind_s( BINDDN, 'DevUser')
	lsearch  =  l.search_s( BASEDN, ldap.SCOPE_SUBTREE, "(&(objectClass=user)(sAMAccountName="+user+"))", ["displayName", "mail", "department"] )
	dn, entry = lsearch[0]
	if dn is not None:
		return entry['mail'][0].decode('UTF-8'), entry['department'][0].decode('UTF-8'), entry['displayName'][0].decode('UTF-8')
	else:
		return False

# Check if user is registered
def isAuthorizedUser( user_id, chat_id ):
	if str( chat_id ) in CCC['auth'] and user_id in CCC['auth'][str(chat_id)]['users']['auth']:
		return CCC['auth'][str(chat_id)]['users']['auth'][user_id]
	else:
		return False

# /register <user>
def register(bot, update, args):
	user_id = update.effective_user.id
	chat_id = str( update.message.chat_id )

	# Create chat dir
	chatdir = REGDIR + '/' + chat_id
	if not os.path.exists( chatdir ):
		os.makedirs( chatdir )

	# Check if userfile exists
	# User is registered and/or authorized
	userfile = chatdir + '/' + str( user_id )
	if os.path.isfile( userfile ):
		with open( userfile, 'rb' ) as f:
			userdict = pickle.load(f)
		if 'authorized' in userdict and userdict['authorized'] == True:
			update.message.reply_text( 'You are already authorized for this chat ' +
						u'\U0001F44D' )
		else:
			update.message.reply_text( 'You have already registered. Check your email' )
			return
	# Userfile doesn't exist
	# User is neither registerd nor authorized
	else:
		if ( len( args) == 1 and args[0].isalpha() and args[0].islower() and len(args[0]) < 15 ):
			mail, dept, name = getUserInfo( args[0] )
			logger.info( "New Registration: chat_id=%s user_id=%s user=%s name=%s mail=%s dept=%s" % 
					( chat_id, str(user_id), args[0], name, mail, dept ) )

			if mail.split('@')[1] == EMAILDOMAIN:

				# Send email with pin
				pin = str(uuid.uuid4())[0:4]
				msg_content = '<h2>'+pin+'</h2><br>Use this pin to authorize <b>/auth pin</b>\n'
				message = MIMEText(msg_content, 'html')
				message['From'] = 'Donot Reply <' + SMTPFROM + '>'
				message['To'] = name + ' <' + mail + '>'
				message['Subject'] = 'Icinga Telegram Verification Code'
				msg_full = message.as_string()
				server = smtplib.SMTP( SMTPSERVER )
				server.sendmail( SMTPFROM, [mail], msg_full )
				server.quit()

				# Create user file
				userdict = { 'id': user_id, 'name': name, 'pin': pin, 'mail': mail, 'authorized': False }
				with open( userfile, 'wb' ) as f:
					pickle.dump( userdict, f )
				# Regenerate CCC
				gen_chat_channels_cache()
				# Inform user
				update.message.reply_text( 'Registered. Check your email' )

# /auth <password>
def auth(bot, update, args):
	user_id = update.effective_user.id
	chat_id = str( update.message.chat_id )
	if ( 	( 'unauth' in CCC and chat_id in CCC['unauth'] and user_id in CCC['unauth'][chat_id]['users']['unauth'] ) or
		( 'auth' in CCC and chat_id in CCC['auth'] and user_id in CCC['auth'][chat_id]['users']['unauth'] ) ):
		# User has registered and is unauthorized
		if ( len( args) == 1 and len( args[0] ) == 4 ):	
			chatdir = REGDIR + '/' + str( chat_id )
			userfile = chatdir + '/' + str( user_id )
			userdict = {}
			if os.path.isfile( userfile ):
				with open( userfile, 'rb' ) as f:
					userdict = pickle.load(f)
				if args[0] == userdict['pin']:
					userdict['authorized'] = True
					with open( userfile, 'wb' ) as f:
						pickle.dump( userdict, f )
					# Regenerate CCC
					gen_chat_channels_cache()
					# Inform user
					update.message.reply_text( 	"Thank you for verification " + u'\U0001F389' +
									"\n\nEnter /channels to select your alerting channels" )

# /channels
def channels( bot, update ):
	user_id = update.effective_user.id
	chat_id = str( update.message.chat_id )
	authuser = isAuthorizedUser( user_id, chat_id )
	if authuser:
		#channels = ', '.join( RegisteredUser['channels'] )
		channels = ', '.join( CCC['auth'][chat_id]['channels'] )
		reply_markup = InlineKeyboardMarkup([
			[ InlineKeyboardButton( ac, callback_data="TogChan;" + ac ) for ac in ALERTCHANNELS ],
			[ InlineKeyboardButton( u'\U00002714', callback_data="TogChan;_DONE_" )]
		])
		update.message.reply_text(	"Your Alert Channels:\n" + "<b>" + channels + "</b>",
						reply_markup=reply_markup, parse_mode=ParseMode.HTML )

# Call back query handler for inline keyboard
def toggleChannel ( bot, update ):
	user_id = update.effective_user.id
	chat_id = str( update.callback_query.message.chat_id )
	authuser = isAuthorizedUser( user_id, chat_id )
	if authuser:
		tc, channel = update.callback_query.data.split(';')
		if channel == '_DONE_':
			update.callback_query.edit_message_reply_markup()
		else:
			chanfiles = [ os.path.basename(ch)[5:] for ch in glob.glob( REGDIR + '/' + chat_id + '/chan-*' ) ]
			if channel in chanfiles:
				os.remove( REGDIR + '/' + chat_id + '/chan-' + channel )
				CCC['auth'][chat_id]['channels'].remove( channel ) 
			else:
				open( REGDIR + '/' + chat_id + '/chan-' + channel , 'a').close()
				CCC['auth'][chat_id]['channels'].add( channel )

			reply_markup = InlineKeyboardMarkup([
				[ InlineKeyboardButton( ac, callback_data="TogChan;" + ac ) for ac in ALERTCHANNELS ],
				[ InlineKeyboardButton( u'\U00002714', callback_data="TogChan;_DONE_" )]
			])
			update.callback_query.edit_message_text( "Your Alert Channels:\n" +
						', '.join( [ "<b>"+a+"</b>" for a in CCC['auth'][chat_id]['channels'] ] ),
						parse_mode=ParseMode.HTML )
			update.callback_query.edit_message_reply_markup( reply_markup=reply_markup )
			update.callback_query.answer()


# Error handling
def error(bot, update, error):
	logger.warn('Update "%s" caused error "%s"' % (update, error))
		

def web(bot, update, args):
	print ( "/web: these args are passed: " + str(args) )
	pass

def status(bot, update):
	pass

def graph(bot, update):
	pass

def ack(bot, update):
	pass

def down(bot, update, args):
	print ( "/downtime: these args are passed: " + str(args) )
	pass

def report(bot, update):
	pass

def main():
	logger.info( "Starting up the script" )
	gen_chat_channels_cache()
	logger.info( "Chat Channel Cache =" + str( CCC ) )

	updater = Updater( BOTTOKEN )
	jq = updater.job_queue
	dp = updater.dispatcher

	# CommandHandlers
	dp.add_handler( CommandHandler("register", register, pass_args=True ) )
	dp.add_handler( CommandHandler("auth", auth, pass_args=True ) )
	dp.add_handler( CommandHandler("web", web, pass_args=True ) )
	dp.add_handler( CommandHandler("status", status, pass_args=True ) )
	dp.add_handler( CommandHandler("graph", graph ) )
	dp.add_handler( CommandHandler("ack", ack, pass_args=True ) )
	dp.add_handler( CommandHandler("downtime", down, pass_args=True ) )
	dp.add_handler( CommandHandler("report", report ) )
	dp.add_handler( CommandHandler("channels", channels ) )

	# CallbackQueryHandlers
	dp.add_handler( CallbackQueryHandler( toggleChannel ) )

	# ErrorHandler
	dp.add_error_handler(error)

	# Start the Job Queue
	jq.run_repeating( icinga_alert_job, 5.0 )

	# Start the Bot
	logger.info( "Starting the bot" )
	updater.start_polling()
	updater.idle()


if __name__ == '__main__':
	main()
