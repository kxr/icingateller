#!/usr/bin/env python3

from telegram.ext import Job, Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
import logging, os, pickle, glob
import ad

# Enable logging
logging.basicConfig( format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
					level=logging.INFO )

logger = logging.getLogger( __name__ )


REGDIR = "/opt/icingateller/registry/"
PASSWORD = "HBMsU"
ICINGAALERTS = "/opt/icingateller/alerts/"
ALERTCHANNELS = [ "EI", "ELS", "EES", "BAN", "TST" ]

# Icinga polling and alerting function
def icinga_alert_job( bot, job ):
	for alertf in glob.glob( ICINGAALERTS + '/*.alert' ):
		with open( alertf, 'r' ) as f:
			alertmsg = f.read()
		alertgroups = os.path.basename( alertf ).split('-')[0].split(';')
		for regfile in glob.glob( REGDIR + '/*' ):
			with open( regfile, 'rb' ) as f:
				userdict = pickle.load(f)
			if bool( set(alertgroups) & set(userdict['channels']) ):
				chat_id = regfile.split('_')[1]
				bot.send_message( chat_id, alertmsg )
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

# Register a user after a correct passphrase is given
def registerUser ( id, first_name, last_name, chat_id ):
	regfile = REGDIR + str( id ) + "_" + str( chat_id )
	userdict = {	'id': id, 'first_name': first_name,
			'last_name': last_name, 'registered': True,
			'channels': [] }
	with open( regfile, 'wb' ) as f:
		pickle.dump( userdict, f )

# Check if user is registered
def isRegisteredUser( id, chat_id ):
	regfile = REGDIR + str( id ) + "_" + str( chat_id )
	if not os.path.isfile( regfile ):
		return False
	else:
		with open( regfile, 'rb') as f:
			regdict = pickle.load(f)
			if 'registered' in regdict and regdict[ 'registered' ] == True:
				return regdict
			else:
				return False

# /start
def start( bot, update ):
	RegisteredUser = isRegisteredUser( update.effective_user.id, update.message.chat_id )
	if not RegisteredUser:
		update.message.reply_text( "Hi " +
			update.effective_user.first_name + " " + update.effective_user.last_name + "\n" +
			"This is the HBMSU Monitoring Bot for receiving monitoring alerts.\n\n" )
	else:
		update.message.reply_text(	"Welcome back " + RegisteredUser['first_name'] + " " + RegisteredUser['last_name'] +
						"\n\nEnter /channels to select your alerting channels" )

# Call back query handler for inline keyboard
def toggleChannel ( bot, update ):
	RegisteredUser = isRegisteredUser( update.effective_user.id, update.callback_query.message.chat_id )
	if RegisteredUser:
		tc, channel, id = update.callback_query.data.split(';')
		regfile = REGDIR + str( id ) + "_" + str( update.callback_query.message.chat_id )
		userdict = {}
		with open( regfile, 'rb' ) as f:
			userdict = pickle.load(f)
		if channel == 'done':
			update.callback_query.edit_message_reply_markup()
		else:
			if 'channels' in userdict:
				if channel in userdict['channels']:
					userdict['channels'].remove(channel)
				else:
					userdict['channels'].append(channel)
			with open( regfile, 'wb' ) as f:
				pickle.dump( userdict, f )

			reply_markup = InlineKeyboardMarkup([
				[ InlineKeyboardButton( ac, callback_data="TogChan;" + ac + ";" + str( id ) ) for ac in ALERTCHANNELS ],
				[ InlineKeyboardButton( u'\U00002714', callback_data="TogChan;done;" + str( id ) )]
			])
			update.callback_query.edit_message_text( "Your Alert Channels:\n" +
						', '.join( [ "<b>"+a+"</b>" for a in userdict['channels'] ] ),
						parse_mode=ParseMode.HTML )
			update.callback_query.edit_message_reply_markup( reply_markup=reply_markup )
			update.callback_query.answer()

# /channels
def channels( bot, update ):
	RegisteredUser = isRegisteredUser( update.effective_user.id, update.message.chat_id )
	if RegisteredUser:
		channels = ', '.join( RegisteredUser['channels'] )
		reply_markup = InlineKeyboardMarkup([
			[ InlineKeyboardButton( ac, callback_data="TogChan;" + ac + ";" + str( RegisteredUser['id'] ) ) for ac in ALERTCHANNELS ],
			[ InlineKeyboardButton( u'\U00002714', callback_data="TogChan;done;" + str( RegisteredUser['id'] ) )]
		])
		update.message.reply_text(	"Your Alert Channels:\n" + "<b>" + channels + "</b>",
						reply_markup=reply_markup, parse_mode=ParseMode.HTML )

# /what
def what( bot, update ):
	update.message.reply_text('You can do the following:\n' +
		'' +
		'')

# message
def message( bot, update, job_queue ):
	RegisteredUser = isRegisteredUser( update.effective_user.id, update.message.chat_id )
	if not RegisteredUser:
		if update.message.text == PASSWORD:
			registerUser(	update.effective_user.id,
					update.effective_user.first_name,
					update.effective_user.last_name,
					update.message.chat_id )
			
			update.message.reply_text( 	"Thank you for verification " + u'\U0001F389' +
							"\n\nEnter /channels to select your alerting channels" )
		else:
			update.message.reply_text( "Bad passphrase! " + u'\U0001F60F' )

# Error handling
def error(bot, update, error):
	logger.warn('Update "%s" caused error "%s"' % (update, error))

# /register <user>
def register(bot, update, args):
	if ( len( args) == 1 ):
		# TODO user input secuirty check on args[0]
		mail, dept, name = getUserInfo( args[0] )
		print( mail + " " + dept + " " + name )

# /auth <password>
def auth(bot, update, args):
	print ( "/auth: these args are passed: " + str(args) )
	pass

def web(bot, update, args):
	print ( "/web: these args are passed: " + str(args) )
	pass

def status(bot, update):
	pass

def graph(bot, update):
	pass

def ack(bot, update):
	pass

def downtime(bot, update, args):
	print ( "/downtime: these args are passed: " + str(args) )
	pass

def report(bot, update):
	pass

def main():
	with open( 'TOKEN', 'r' ) as f:
		BOTTOKEN = f.read().splitlines()[0]
	updater = Updater( BOTTOKEN )
	jq = updater.job_queue
	dp = updater.dispatcher

	# CommandHandlers
	dp.add_handler( CommandHandler("start", start ) )
	dp.add_handler( CommandHandler("register", register, pass_args=True ) )
	dp.add_handler( CommandHandler("auth", auth, pass_args=True ) )
	dp.add_handler( CommandHandler("web", web, pass_args=True ) )
	dp.add_handler( CommandHandler("status", status, pass_args=True ) )
	dp.add_handler( CommandHandler("graph", graph ) )
	dp.add_handler( CommandHandler("ack", ack, pass_args=True ) )
	dp.add_handler( CommandHandler("downtime", down, pass_args=True ) )
	dp.add_handler( CommandHandler("report", report ) )
	dp.add_handler( CommandHandler("channels", channels ) )
	dp.add_handler( CommandHandler("what", what) )

	# CallbackQueryHandlers
	dp.add_handler( CallbackQueryHandler( toggleChannel ) )

	# MessageHandlers
	dp.add_handler(MessageHandler(Filters.text, message ) )

	# ErrorHandler
	dp.add_error_handler(error)

	# Start the Job Queue
	jq.run_repeating( icinga_alert_job, 5.0 )

	# Start the Bot
	updater.start_polling()
	updater.idle()


if __name__ == '__main__':
	main()
