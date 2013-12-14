# Point-and-shoot camera for Raspberry Pi w/camera and Adafruit PiTFT
# Button #4 (pin 18) takes picture (outputs image.jpg)
# Button #3 (pin 27) exits
# Must run as root (sudo python cam.py) due to GPIO, framebuffer, etc.

import os
import io
import time
import pygame
import picamera
import RPi.GPIO as GPIO
import yuv2rgb

os.putenv('SDL_VIDEODRIVER', 'fbcon')
os.putenv('SDL_FBDEV'      , '/dev/fb1')

GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(27, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Buffers for preview image data
rgb = bytearray(320 * 240 * 3)
yuv = bytearray(320 * 240 * 3 / 2)

pygame.init()
pygame.mouse.set_visible(False)
clock  = pygame.time.Clock()
screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)

camera            = picamera.PiCamera()
camera.resolution = (320, 240)
# Leave raw format at default YUV, don't touch!

try:
	while(True):
                if(GPIO.input(27) == GPIO.LOW):
			break

                if(GPIO.input(18) == GPIO.LOW):
			camera.resolution = (2592, 1944)
			camera.capture('image.jpg',
			  use_video_port=False, format='jpeg')
			img = pygame.image.load('image.jpg')
# need to scale result here
#			screen.blit(img,(0,0))
#			pygame.display.update()
#			time.sleep(3)
                        while(GPIO.input(18) == GPIO.LOW): pass
			camera.resolution = (320,240)

		stream = io.BytesIO()
		camera.capture(stream,
		  use_video_port=True, format='raw')
		stream.seek(0)
		stream.readinto(yuv)
		stream.close()

		yuv2rgb.convert(yuv, rgb, 320, 240)

                im = pygame.image.frombuffer(rgb, (320,240), 'RGB')
                screen.blit(im, (0, 0))
		pygame.display.update()
#		clock.tick()
#		print(clock.get_fps())

finally:
	camera.close()
	GPIO.cleanup()
