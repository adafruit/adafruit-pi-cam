# Point-and-shoot camera for Raspberry Pi w/camera and Adafruit PiTFT.
# This must run as root (sudo python cam.py) due to framebuffer, etc.
#
# Adafruit invests time and resources providing this open source code, 
# please support Adafruit and open-source development by purchasing 
# products from Adafruit, thanks!
#
# http://www.adafruit.com/products/998
# http://www.adafruit.com/products/1367
# http://www.adafruit.com/products/1601
#
# Written by Phil Burgess / Paint Your Dragon for Adafruit Industries.
# BSD license, all text above must be included in any redistribution.


# TO DO:
# Dropbox upload
# Image playback



import cPickle as pickle
import errno
import fnmatch
import io
import os
import picamera
import pygame
import stat
import threading
import time
import yuv2rgb
from pygame.locals import *


# Some global stuff --------------------------------------------------------

imgNum         =  0      # Image index for saving
screenMode     =  0      # Current screen mode; default = viewfinder
settingMode    =  3      # Last-used settings mode (default = storage)
storeMode      =  0      # Storage mode; default = Photos folder
storeModePrior = -1      # Prior storage mode (for detecting changes)
sizeMode       =  0      # Image size; default = Large
fxMode         =  0      # Image effect; default = Normal
isoMode        =  0      # ISO settingl default = Auto
iconPath       = 'icons' # Subdirectory containing UI bitmaps (PNG format)

sizeData = [ # Camera parameters for different size settings
 # Full res      Viewfinder  Crop window
 [(2592, 1944), (320, 240), (0.0   , 0.0   , 1.0   , 1.0   )], # Large
 [(1920, 1080), (320, 180), (0.1296, 0.2222, 0.7408, 0.5556)], # Med
 [(1440, 1080), (320, 240), (0.2222, 0.2222, 0.5556, 0.5556)]] # Small

isoData = [ # Values for ISO settings (ISO value, indicator X position)
 [  0,  27], [100,  64], [200,  97], [320, 137],
 [400, 164], [500, 197], [640, 244], [800, 297]]

# A fixed list of image effects is used (rather than polling
# camera.IMAGE_EFFECTS) because the latter contains a few elements
# that aren't valid (at least in video_port mode) -- e.g. blackboard,
# whiteboard, posterize (but posterise, British spelling, is OK).
# Others have no visible effect (or might require setting add'l
# camera parameters for which there's no GUI yet) -- e.g. saturation,
# colorbalance, colorpoint.
fxData = [
  'none', 'sketch', 'gpen', 'pastel', 'watercolor', 'oilpaint', 'hatch',
  'negative', 'colorswap', 'posterise', 'denoise', 'blur', 'film',
  'washedout', 'emboss', 'cartoon', 'solarize' ]

pathData = [
  '/home/pi/Photos',     # Path for storeMode = 0
  '/boot/DCIM/CANON999', # Path for storeMode = 1
  '/tmp']                # Path for storeMode = 2

# The final global -- the big Buttons list -- isn't declared until
# after initialization as it requires the Icon list be initialized first.


# UI classes ---------------------------------------------------------------

# Small resistive touchscreen is best suited to simple tap interactions.
# Importing a big widget library seemed a bit overkill.  Instead, a couple
# of simplistic classes are sufficient for the UI elements:

# Icon is a very simple bitmap class, just associates a name and a pygame
# image (PNG loaded from icons directory) for each.

class Icon:

	def __init__(self, name):
	  self.name = name
	  try:
	    self.bitmap = pygame.image.load(iconPath + '/' + name + '.png')
	  except:
	    pass

# Button is a simple tappable screen region.  Each has:
#  - bounding rect ((X,Y,W,H) in pixels)
#  - optional background color and/or Icon (or None), always centered
#  - optional foreground Icon, always centered
#  - optional single callback function
#  - optional single value passed to callback
# Occasionally Buttons are used as a convenience for positioning Icons
# but the taps are ignored.  Stacking order is important; when Buttons
# overlap, lowest/first Button in list takes precedence when processing
# input, and highest/last Button is drawn atop prior Button(s).  This is
# used, for example, to center an Icon by creating a passive Button the
# width of the full screen, but with other buttons left or right that
# may take input precedence (e.g. the Effect labels & buttons).

class Button:

	def __init__(self, rect, **kwargs):
	  self.rect     = rect # Bounds
	  self.color    = None # Background fill color, if any
	  self.iconBg   = None # Background icon (atop color fill)
	  self.iconFg   = None # Foreground icon (atop background)
	  self.callback = None # Callback function
	  self.value    = None # Value passed to callback
	  for key, value in kwargs.iteritems():
	    if key == 'color':
	      self.color = value
	    elif key == 'bg':
	      for i in icons:
	        if value == i.name:
	          self.iconBg = i
	          break
	    elif key == 'fg':
	      for i in icons:
	        if value == i.name:
	          self.iconFg = i
	          break
	    elif key == 'cb':
	      self.callback = value
	    elif key == 'value':
	      self.value    = value

	def selected(self, pos):
	  x1 = self.rect[0]
	  y1 = self.rect[1]
	  x2 = x1 + self.rect[2] - 1
	  y2 = y1 + self.rect[3] - 1
	  if ((pos[0] >= x1) and (pos[0] <= x2) and
	      (pos[1] >= y1) and (pos[1] <= y2)):
	    if self.callback:
	      if self.value is None: self.callback()
	      else:                  self.callback(self.value)
	    return True
	  return False

	def draw(self, screen):
	  if self.color:
	    screen.fill(self.color, self.rect)
	  if self.iconBg:
	    screen.blit(self.iconBg.bitmap,
	      (self.rect[0]+(self.rect[2]-self.iconBg.bitmap.get_width())/2,
	       self.rect[1]+(self.rect[3]-self.iconBg.bitmap.get_height())/2))
	  if self.iconFg:
	    screen.blit(self.iconFg.bitmap,
	      (self.rect[0]+(self.rect[2]-self.iconFg.bitmap.get_width())/2,
	       self.rect[1]+(self.rect[3]-self.iconFg.bitmap.get_height())/2))

	def setBg(self, name):
	  if name is None:
	    self.iconBg = None
	  else:
	    for i in icons:
	      if name == i.name:
	        self.iconBg = i
	        break


# Assorted utility functions -----------------------------------------------

def setFxMode(n):
	global fxMode
	fxMode = n
	camera.image_effect = fxData[fxMode]
	buttons[5][5].setBg('fx-' + fxData[fxMode])

def setIsoMode(n):
	global isoMode
	isoMode    = n
	camera.ISO = isoData[isoMode][0]
	buttons[6][5].setBg('iso-' + str(isoData[isoMode][0]))
	buttons[6][7].rect = ((isoData[isoMode][1] - 10,) +
	  buttons[6][7].rect[1:])

def setSizeMode(n):
	global sizeMode
	buttons[4][sizeMode + 3].setBg('radio3-0')
	sizeMode = n
	buttons[4][sizeMode + 3].setBg('radio3-1')
	camera.resolution = sizeData[sizeMode][1]
	camera.crop       = sizeData[sizeMode][2]

def setStoreMode(n):
	global storeMode
	buttons[3][storeMode + 3].setBg('radio3-0')
	storeMode = n
	buttons[3][storeMode + 3].setBg('radio3-1')

def saveSettings():
	try:
	  outfile = open('cam.pkl', 'wb')
	  # Use a dictionary (rather than pickling 'raw' values) so
	  # the number & order of things can change without breaking.
	  d = { 'fx'    : fxMode,
	        'iso'   : isoMode,
	        'size'  : sizeMode,
	        'store' : storeMode }
	  pickle.dump(d, outfile)
	  outfile.close()
	except:
	  pass

def loadSettings():
	try:
	  infile = open('cam.pkl', 'rb')
	  d      = pickle.load(infile)
	  infile.close()
	  if 'fx'    in d: setFxMode(   d['fx'])
	  if 'iso'   in d: setIsoMode(  d['iso'])
	  if 'size'  in d: setSizeMode( d['size'])
	  if 'store' in d: setStoreMode(d['store'])
	except:
	  pass

# Scan files in a directory, locating JPEGs with names matching the
# software's convention (IMG_XXXX.JPG), returning a tuple with the
# lowest and highest indices.
def maxImg(path):
	min = 9999
	max = 0
	for file in os.listdir(path):
	  if fnmatch.fnmatch(file, 'IMG_[0-9][0-9][0-9][0-9].JPG'):
	    i = int(file[4:8])
	    if(i < min): min = i
	    if(i > max): max = i
	return (min, max)

def spinner():
	global busy

	buttons[0][3].setBg('working')
	buttons[0][3].draw(screen)
	pygame.display.update()

	n = 0
	while busy is True:
	  buttons[0][4].setBg('work-' + str(n))
	  buttons[0][4].draw(screen)
	  pygame.display.update()
	  n = (n + 1) % 5
	  time.sleep(0.15)

	buttons[0][3].setBg(None)
	buttons[0][4].setBg(None)

def takePicture():
	global imgNum, storeModePrior, scaled, busy

	if not os.path.isdir(pathData[storeMode]):
	  try:
	    # This theoretically is only necessary for the 'Photos' dir
	    os.makedirs(pathData[storeMode])
	    # Set new directory ownership to pi user, mode to 755
	    os.chown(pathData[storeMode], uid, gid)
	    os.chmod(pathData[storeMode],
	      stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
	      stat.S_IRGRP | stat.S_IXGRP |
	      stat.S_IROTH | stat.S_IXOTH)
	  except OSError as e:
	    # errno = 2 if can't create folder
	    print errno.errorcode[e.errno]
	    return

	# If this is the first time accessing this directory,
	# scan for the max image index, start at next pos.
	if storeMode != storeModePrior:
	  imgNum = maxImg(pathData[storeMode])[1] + 1
	  if imgNum > 9999: imgNum = 0
	  storeModePrior = storeMode

	# Scan for next available image slot
	while True:
	  filename = pathData[storeMode] + '/IMG_' + '%04d' % imgNum + '.JPG'
	  if not os.path.isfile(filename): break
	  imgNum += 1
	  if imgNum > 9999: imgNum = 0

	t    = threading.Thread(target=spinner)
	busy = True
	t.start()

	camera.resolution = sizeData[sizeMode][0]
	try:
	  camera.capture(filename, use_video_port=False, format='jpeg',
	    thumbnail=None)
	  # Set image file ownership to pi user, mode to 644
	  os.chown(filename, uid, gid)
	  os.chmod(filename,
	    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
	  img    = pygame.image.load(filename)
	  scaled = pygame.transform.scale(img, sizeData[sizeMode][1])
	finally:
	  # Add error handling/indicator (disk full, etc.)
	  camera.resolution = sizeData[sizeMode][1]

	busy = False
	t.join()

	if scaled:
	  if sizeData[sizeMode][1][1] < 240: # Letterbox
	    screen.fill(0)
	  screen.blit(scaled, ((320 - sizeData[sizeMode][1][0]) / 2,
	    (240 - sizeData[sizeMode][1][1]) / 2))
	  pygame.display.update()
	  time.sleep(2.5)
	  scaled = None



# UI callbacks -------------------------------------------------------------

def isoCallback(n): # Pass 1 (next ISO) or -1 (prev ISO)
	global isoMode
	setIsoMode((isoMode + n) % len(isoData))

def settingCallback(n): # Pass 1 (next setting) or -1 (prev setting)
	global screenMode
	screenMode += n
	if screenMode < 3:               screenMode = len(buttons) - 1
	elif screenMode >= len(buttons): screenMode = 3

def fxCallback(n): # Pass 1 (next effect) or -1 (prev effect)
	global fxMode
	setFxMode((fxMode + n) % len(fxData))

def quitCallback():
	doneCallback() # Save settings
	raise SystemExit

def viewCallback(n):
	global screenMode
	if   n is 0: screenMode = settingMode # Switch to last settings mode
	elif n is 1: screenMode = 1           # Switch to playback mode
	else:        takePicture()

def doneCallback():
	global screenMode, settingMode
	if screenMode > 2:
	  settingMode = screenMode
	  saveSettings()
	screenMode = 0 # Switch back to viewfinder mode

def imageCallback(n): # Pass 1 (next image), -1 (prev image) or 0 (delete)
	global screenMode
	if n is 0:
	  screenMode = 2 # Delete confirmation
	elif n is -1:
	  pass
	else:
	  pass

def deleteCallback(n):
	global screenMode
	if n is True:
	  pass
	else:
	  pass
	screenMode = 1 # Switch back to playback mode

# Initialization -----------------------------------------------------------


# Init framebuffer/touchscreen environment variables
os.putenv('SDL_VIDEODRIVER', 'fbcon')
os.putenv('SDL_FBDEV'      , '/dev/fb1')
os.putenv('SDL_MOUSEDRV'   , 'TSLIB')
os.putenv('SDL_MOUSEDEV'   , '/dev/input/touchscreen')

# Get user & group IDs for file & folder creation
# (Want these to be 'pi' or other user, not root)
s = os.getenv("SUDO_UID")
uid = int(s) if s else os.getuid()
s = os.getenv("SUDO_GID")
gid = int(s) if s else os.getgid()

# Buffers for viewfinder data
rgb = bytearray(320 * 240 * 3)
yuv = bytearray(320 * 240 * 3 / 2)

# Init pygame and screen
pygame.init()
pygame.mouse.set_visible(False)
screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)

# Init camera and set up default values
camera            = picamera.PiCamera()
camera.resolution = sizeData[sizeMode][1]
camera.crop       = sizeData[sizeMode][2]
# Leave raw format at default YUV, don't touch, don't set to RGB!

# Load all icons at startup.  Must do this before Buttons are declared.
icons = []
for file in os.listdir(iconPath):
  if fnmatch.fnmatch(file, '*.png'):
    icons.append(Icon(file.split('.')[0]))

# The buttons[] list sits down here (rather than with the other global
# declarations above) as the icons[] list needs to be loaded up first.
# It's a list of lists; each top-level list element corresponds to one
# screen mode (e.g. viewfinder, image playback, storage settings), and
# each element within those lists corresponds to one UI button.
# There's a little bit of repetition (e.g. prev/next buttons are
# declared for each settings screen, rather than a single reusable
# set); trying to reuse those few elements just made for an ugly
# tangle of code elsewhere.

buttons = [
  # Screen mode 0 is viewfinder / snapshot
  [Button((  0,188,156, 52), bg='gear', cb=viewCallback, value=0),
   Button((164,188,156, 52), bg='play', cb=viewCallback, value=1),
   Button((  0,  0,320,240)           , cb=viewCallback, value=2),
   Button(( 88, 51,157,102)),  # 'Working' goes here
   Button((148, 110,22, 22))], # Spinner goes here

  # Screen mode 1 is photo playback
  [Button((  0,188,320,52), bg='done' , cb=doneCallback),
   Button((  0,  0, 80,52), bg='prev' , cb=imageCallback, value=-1),
   Button((240,  0, 80,52), bg='next' , cb=imageCallback, value= 1),
   Button((121,  0, 78,52), bg='trash', cb=imageCallback, value= 0)],

  # Screen mode 2 is delete confirmation
  [Button((  0,35,320, 33), bg='delete'),
   Button(( 32,86,120,100), bg='yn', fg='yes',
    cb=deleteCallback, value=True),
   Button((168,86,120,100), bg='yn', fg='no',
    cb=deleteCallback, value=False)],

  # Remaining screens are settings modes

  # Screen mode 3 is storage settings
  [Button((  0,188,320, 52), bg='done', cb=doneCallback),
   Button((  0,  0, 80, 52), bg='prev', cb=settingCallback, value=-1),
   Button((240,  0, 80, 52), bg='next', cb=settingCallback, value= 1),
   Button((  2, 60,100,120), bg='radio3-1', fg='store-folder',
    cb=setStoreMode, value=0),
   Button((110, 60,100,120), bg='radio3-0', fg='store-boot',
    cb=setStoreMode, value=1),
   Button((218, 60,100,120), bg='radio3-0', fg='store-dropbox',
    cb=setStoreMode, value=2),
   Button((  0, 10,320, 35), bg='storage')],

  # Screen mode 4 is size settings
  [Button((  0,188,320, 52), bg='done', cb=doneCallback),
   Button((  0,  0, 80, 52), bg='prev', cb=settingCallback, value=-1),
   Button((240,  0, 80, 52), bg='next', cb=settingCallback, value= 1),
   Button((  2, 60,100,120), bg='radio3-1', fg='size-l',
    cb=setSizeMode, value=0),
   Button((110, 60,100,120), bg='radio3-0', fg='size-m',
    cb=setSizeMode, value=1),
   Button((218, 60,100,120), bg='radio3-0', fg='size-s',
    cb=setSizeMode, value=2),
   Button((  0, 10,320, 29), bg='size')],

  # Screen mode 5 is graphic effect
  [Button((  0,188,320, 52), bg='done', cb=doneCallback),
   Button((  0,  0, 80, 52), bg='prev', cb=settingCallback, value=-1),
   Button((240,  0, 80, 52), bg='next', cb=settingCallback, value= 1),
   Button((  0, 70, 80, 52), bg='prev', cb=fxCallback     , value=-1),
   Button((240, 70, 80, 52), bg='next', cb=fxCallback     , value= 1),
   Button((  0, 67,320, 91), bg='fx-none'),
   Button((  0, 11,320, 29), bg='fx')],

  # Screen mode 6 is ISO
  [Button((  0,188,320, 52), bg='done', cb=doneCallback),
   Button((  0,  0, 80, 52), bg='prev', cb=settingCallback, value=-1),
   Button((240,  0, 80, 52), bg='next', cb=settingCallback, value= 1),
   Button((  0, 70, 80, 52), bg='prev', cb=isoCallback    , value=-1),
   Button((240, 70, 80, 52), bg='next', cb=isoCallback    , value= 1),
   Button((  0, 79,320, 33), bg='iso-0'),
   Button((  9,134,302, 26), bg='iso-bar'),
   Button(( 17,157, 21, 19), bg='iso-arrow'),
   Button((  0, 10,320, 29), bg='iso')],

  # Screen mode 7 is quit confirmation
  [Button((  0,188,320, 52), bg='done'   , cb=doneCallback),
   Button((  0,  0, 80, 52), bg='prev'   , cb=settingCallback, value=-1),
   Button((240,  0, 80, 52), bg='next'   , cb=settingCallback, value= 1),
   Button((110, 60,100,120), bg='quit-ok', cb=quitCallback),
   Button((  0, 10,320, 35), bg='quit')],

]

loadSettings() # Must come after buttons[] declaration


# Main loop ----------------------------------------------------------------

try:
	while(True):

# If screenMode is 1 (playback) or 2 (confirm delete), operation is
# entirely event driven,
# there's no need to continually update screen.
# But the handling of button presses is similar.
# Clear background,
# Keep track of image # being viewed (distinct from imgNum, the
# last recorded -- but we can use that as the starting value).
# Left and right buttons then seek back and forward through index.
# If a complete loop is made or if directory is empty, display a
# "no images" (or no photos) prompt.  Does not need an OK button,
# just use the 'Done' button.
# Also, monitor trash icon.  If clicked, delete that image,
# advance backward? or forward?
# Should it go in a totally separate event loop?

	  for event in pygame.event.get():
	    if(event.type is MOUSEBUTTONDOWN):
	      pos = pygame.mouse.get_pos()
	      for b in buttons[screenMode]:
	        if b.selected(pos): break

	  stream = io.BytesIO()
	  camera.capture(stream, use_video_port=True, format='raw')
	  stream.seek(0)
	  stream.readinto(yuv)
	  stream.close()
	  yuv2rgb.convert(yuv, rgb, sizeData[sizeMode][1][0],
	    sizeData[sizeMode][1][1])
	  im = pygame.image.frombuffer(rgb[0:
	    (sizeData[sizeMode][1][0] * sizeData[sizeMode][1][1] * 3)],
	    sizeData[sizeMode][1], 'RGB')
	  if sizeData[sizeMode][1][1] < 240: # Letterbox
	    screen.fill(0)
	  screen.blit(im, ((320 - sizeData[sizeMode][1][0]) / 2,
	    (240 - sizeData[sizeMode][1][1]) / 2))

	  for i,b in enumerate(buttons[screenMode]):
	    b.draw(screen)
	  pygame.display.update()

finally:
	camera.close()

