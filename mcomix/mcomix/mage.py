'''mage.py - the i(nternal)mage class.'''

from binascii import unhexlify
from io import BytesIO

from gi.repository import Gio

# the 'Pixbuf' instance
from gi.repository import GdkPixbuf
# the 'PImage' instance
from PIL import Image

def _pixbuf2pil(pixbuf):
    mode='RGBA' if pixbuf.get_has_alpha() else 'RGB'
    return Image.frombuffer(mode,(pixbuf.get_width(),pixbuf.get_height()),
                            pixbuf.get_pixels(),'raw',mode,pixbuf.get_rowstride(),1)

def _getexif(im):
    exif={}
    try:
        exif.update(im.getexif())
    except AttributeError:
        pass
    if exif:
        return exif

    # exif of PNG is still buggy in Pillow 6.0.0
    try:
        l1,l2,size,*lines=im.info.get('Raw profile type exif').splitlines()
    except:
        # invalid exif data.
        return {}
    if l2!='exif':
        # invalid exif data.
        return {}
    if len(data:=unhexlify(''.join(lines)))!=int(size):
        # size not match.
        return {}
    im.info['exif']=data

    # reload exif
    try:
        exif.update(im.getexif())
    except AttributeError:
        pass
    return exif

class GioStreamIO(Gio.MemoryInputStream):
    def __init__(self,data=b''):
        super().__init__()
        if data:
            self.add_data(data)

    def __enter__(self):
        return self

    def __exit__(self,etype,value,tb):
        self.close()

class Mage:
    def __init__(self):

        # original image as PImage, or the first frame of animation
        self._im=None
        # a list of (PImage,int), as the frame and duration
        # if image is not animation, it should be empty.
        self._frames=[]
        # loop animation
        self._loop=False
        # original background color as int (#RRGGBBAA).
        self._bgcolor=0
        # bytes data of color profile, or None.
        self._icc=None
        # dictionary of exif, or None.
        self._exif={}

        # cached image as PImage
        self._cache=None
        # cached image object, a list of (PImage,int)
        self._cache_frames=[]
        # background color of cache as int (#RRGGBBAA) or checkered bg as -1
        self._bg=0
        # rotation of cache from original, should be in (0, 90, 180, 270).
        self._rotation=0
        # scale filter of cache.
        self._filter=None
        # size of cache
        self._size=None

        # thumbnail as Pixbuf.
        # fast scale filter, no icc, no animation.
        self._thumbnail=None

    @property
    def image(self):
        # access to original image.
        if self._im is None:
            raise ValueError('image is not loaded')
        return self._im

    @image.setter
    def image(self,im):
        # set or update original image, close previous image.
        if self._im is not None:
            _im=self._im
            self._im=None
            _im.close()
            self._exif.clear()
            self.purge_frames()
        self._im=im
        self._bgcolor=0
        self._icc=im.info.get('icc_profile')
        self._exif.update(_getexif(im))
        self._size=im.size

    @property
    def frames(self):
        # access to original frames
        return self._frames

    def add_frame(self,frame,duration):
        self.frames.append((frame,duration))

    def purge_frames(self):
        # purge all frames
        while self.frames:
            im,duration=self.frames.pop()
            im.close()

    @property
    def cache(self):
        # get cached image, generate if not cached yet.
        raise NotImplementedError('property: Mage.cache')

    @cache.setter
    def cache(self,im):
        # set or update cached image, close previous cache and update cache parameters.
        raise NotImplementedError('setter: Mage.cache')

    def purge_cache(self):
        # purge cached image and all cached frames
        if self._cache is not None:
            _cache=self._cache
            self._cache=None
            _cache.close()
            while self._cache_frames:
                im,duration=self._cache_frames.pop()
                im.close()

    @property
    def original_size(self):
        # get the (width, height) of the original image
        return self.image.size

    @property
    def size(self):
        # get the (width, height) of the cached image
        return self._size

    @size.setter
    def size(self,width,height):
        # set the width and height of the cached image
        if tuple(self.size)!=(width,height):
            self.purge_cache()
        self._size=(width,height)

    @property
    def rotation(self):
        # get the rotation of the cached image
        return self._rotation

    @rotation.setter
    def rotation(self,rotation):
        if rotation!=self.rotation:
            self.purge_cache()
        self._rotation=rotation

    def _load_fallback(self,data,animation=False,n_frames=1):
        # load image from data using GdkPixbuf.
        loader=GdkPixbuf.PixbufAnimation if animation else GdkPixbuf.Pixbuf
        with GioStreamIO(data) as stream:
            pixbuf=loader.new_from_stream(stream)
            if not animation or n_frames<2:
                # return static image if n_frames is less than 2.
                # GdkPixbuf.PixbufAnimation does not report total frames.
                self.image=_pixbuf2pil(pixbuf)
                return
            self.image=_pixbuf2pil(pixbuf.get_static_image())
            frame_iter=pixbuf.get_iter(cur:=GLib.TimeVal())
            for n in range(im.n_frames):
                cur.add((delay:=frame_iter.get_delay_time())*1000)
                frame=(frame_ref:=frame_iter.get_pixbuf()).copy()
                frame_ref.copy_options(frame)
                self.add_frame(_pixbuf2pil(frame),delay)
                if n==im.n_frames-1:
                    return
                while not frame_iter.advance(cur):
                    cur.add(frame_iter.get_delay_time()*1000)

    def load(self,data,enable_anime=False):
        # load image from data, set to self.image and append to self.frames.
        try:
            im=Image.open(BytesIO(data))
            im.load()
        except:
            # unsupported by PIL, fallback to GdkPixbuf.
            # disable animation if unsupported by PIL.
            return self._load_fallback(data)
        if not (enable_anime and getattr(im,'is_animated',False)):
            self.image=im
            return
        if im.format=='GIF' and im.mode=='P':
            # fallback to GdkPixbuf for gif animation
            # See https://github.com/python-pillow/Pillow/labels/GIF
            self._load_fallback(data,animation=True,n_frames=im.n_frames)
        else:
            for n,frame in enumerate(ImageSequence.Iterator(im)):
                if n==0:
                    self.image=frame
                self.add_frame(frame,int(frame.info.get('duration',0)))
            if isinstance(background:=im.info.get('background',0),tuple):
                self._bgcolor=int(''.join(f'{c:02x}' for c in background),16)
            else:
                self._bgcolor=background
        self._loop=im.info['loop']

    # TODO: more property and method

# Local Variables:
# coding: utf-8
# mode: python
# python-indent-offset: 4
# indent-tabs-mode: nil
# End:
