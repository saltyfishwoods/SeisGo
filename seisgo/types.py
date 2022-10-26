#define key classes
import os,sys,pickle,obspy,scipy,pyasdf
from obspy.core import Trace,Stream
import numpy as np
import matplotlib.pyplot as plt
from obspy.io.sac.sactrace import SACTrace
from obspy.signal.filter import bandpass,highpass,lowpass
from scipy.fftpack import fft,ifft,fftfreq,next_fast_len
from seisgo import utils,stacking,helpers
from obspy import UTCDateTime
from scipy import signal
######
class SeismicEngine(object):
    """
    Engine to interactively display time series data.
    """
    def __init__(self):
        self.type="Seismic Engine"

class Station(object):
    """
    Container for basic station information. Doesn't intend to replace the inventory class in ObsPy.

    Attributes
    -----------
    net: network name
    sta: station name
    loc: location code
    lon: longitude
    lat: latitude
    ele: elevation
    """
    def __init__(self, net=None,sta=None,loc=None,chan=None,lon=None, lat=None, ele=None):
        self.net = net
        self.sta = sta
        self.loc = loc
        self.chan = chan
        self.lon = lon
        self.lat = lat
        self.ele = ele

    def __str__(self):
        """
        Display key content of the object.
        """
        print("network      :   "+str(self.net))
        print("station      :   "+str(self.sta))
        print("location     :   "+str(self.loc))
        print("channel      :   "+str(self.chan))
        print("longitude   :   "+str(self.lon))
        print("latitude    :   "+str(self.lat))
        print("elevation   :   "+str(self.ele))

        print("")

        return "<Station object>"

class RawData(object):
    """
    Object to store seismic waveforms. When in three components, there is an option
    to do rotation from ENZ system to RTZ or LQT systems. The component labels will be
    renewed after rotation. This object is useful particularly in receiver function
    processing.
    """
    def __init__(self,trlist,stlo,stla,stel,stloc=None,stainv=None,evlo=None,evlat=None,evdp=None,evmag=None,evmagtype=None,
                    quake_ml=None,misc=dict()):
        """
        Initialize the object.

        trlist: a list of obspy.core.Trace object or a Stream object. Please make sure the list is for
                different channels when more than one trace in the list, NOT the segments with gaps for
                one station-channel pair.
        """
        if stainv is not None:
            self.sta,self.net,self.lon,self.lat,self.ele,self.loc = utils.sta_info_from_inv(stainv)
        elif None not in [stlo,stla,stel]:
            self.net=trace[0].stats.network
            self.sta=trace[0].stats.station
            self.stlo=stlo
            self.stla=stla
            self.stel=stel
            if stloc is None:
                self.stloc=''
            else: self.stloc=stloc

class RFData(object):
    """
    Reciever function data.
    """
    def __init__(self):
        self.type='Receiver Function Data'

class FFTData(object):
    """
    Object to store FFT data. The idea of having a FFTData data type
    was originally designed by Tim Clements for SeisNoise.jl (https://github.com/tclements/SeisNoise.jl).
    """
    def __init__(self,trace=None,win_len=None,step=None,stainv=None,
                id=None,net=None,sta=None,loc=None,chan=None,lon=None,lat=None,ele=None,
                dt=None,std=None,time=None,Nfft=None,data=None,
                 freqmin=None,freqmax=None,time_norm='no',freq_norm='no',smooth=20,
                 smooth_spec=None,misc=dict(),taper_frac=0.05,df=None):
        if trace is None:
            self.type='FFT Data'
            self.id=id
            self.net=net
            self.sta=sta
            self.loc=loc
            self.chan=chan
            self.lon=lon
            self.lat=lat
            self.ele=ele
            self.dt=dt
            self.freqmin=freqmin
            self.freqmax=freqmax
            self.time_norm=time_norm
            self.freq_norm=freq_norm
            self.df=df
            self.smooth=smooth
            self.smooth_spec=smooth_spec
            self.win_len=win_len
            self.step=step
            self.std=std
            self.time=time
            self.Nfft=Nfft
            self.misc=misc
            self.data=data
        else:
            self.construct(trace,win_len,step,stainv=stainv,
                         freqmin=freqmin,freqmax=freqmax,time_norm=time_norm,
                         freq_norm=freq_norm,smooth=smooth,
                         smooth_spec=smooth_spec,misc=misc,taper_frac=taper_frac,df=df)

    def construct(self,trace,win_len,step,stainv=None,
                     freqmin=None,freqmax=None,time_norm='no',freq_norm='no',smooth=20,
                     smooth_spec=None,misc=dict(),taper_frac=0.05,df=None):
        """
        Constructure the FFTData object. Will do whitening if specicied in freq_norm.

        trace: obspy.core.Trace or Stream object.
        """
        self.type='FFT Data'
        if isinstance(trace,Trace):trace=Stream([trace])

        if stainv is not None:
            self.sta,self.net,self.lon,self.lat,self.ele,self.loc = utils.sta_info_from_inv(stainv)
        else:
            self.net=trace[0].stats.network
            self.sta=trace[0].stats.station
            self.lon=0.0
            self.lat=0.0
            self.ele=0.0
            self.loc=''
        if isinstance(self.sta,list):self.sta=self.sta[0]
        if isinstance(self.net,list):self.net=self.net[0]
        if isinstance(self.lon,list):self.lon=self.lon[0]
        if isinstance(self.lat,list):self.lat=self.lat[0]
        if isinstance(self.ele,list):self.ele=self.ele[0]
        if isinstance(self.loc,list):self.loc=self.loc[0]

        self.chan=trace[0].stats.channel
        self.id=self.net+'.'+self.sta+'.'+self.loc+'.'+self.chan
        self.dt = 1/trace[0].stats.sampling_rate
        self.freqmin=freqmin
        self.freqmax=freqmax
        self.df = df
        if df is None and self.freqmin is not None:
            self.df = self.freqmin/4

        self.time_norm=time_norm
        self.freq_norm=freq_norm
        self.smooth=smooth
        if smooth_spec is None:
            self.smooth_spec=self.smooth
        else:
            self.smooth_spec=smooth_spec
        self.win_len=win_len
        self.step=step
        self.misc=misc

        fft_white=[]
        tr=trace[0].copy()
        if time_norm == 'ftn':
            if self.freqmin is not None:
                if self.freqmax is None:self.freqmax=0.499/self.dt
                tr.data=utils.ftn(trace[0].data,self.dt,self.freqmin,self.freqmax,df=self.df)
            else:
                raise ValueError("freqmin must be specified with ftn normalization.")
        # cut data into smaller segments (dataS always in 2D)
        trace_stdS,dataS_t,dataS = utils.slicing_trace([tr],win_len,step,
                                                        taper_frac=taper_frac)        # optimized version:3-4 times faster

        if len(dataS)>0:
            N=dataS.shape[0]
            self.std=trace_stdS
            self.time=dataS_t
            #------to normalize in time or not------
            if time_norm != 'no':
                if time_norm == 'one_bit': 	# sign normalization
                    white = np.sign(dataS)
                elif time_norm == 'rma': # running mean: normalization over smoothed absolute average
                    white = np.zeros(shape=dataS.shape,dtype=dataS.dtype)
                    for kkk in range(N):
                        white[kkk,:] = dataS[kkk,:]/utils.moving_ave(np.abs(dataS[kkk,:]),smooth)
                elif time_norm == 'ftn':
                    white = dataS
                else:
                    raise ValueError("The input "+time_norm+" is not recoganizable. "+
                            "Could only be: no, one_bit, ftn, or rma.")
            else:	# don't normalize
                white = dataS

            #-----to whiten or not------

            if white.ndim == 1:
                axis = 0
            elif white.ndim == 2:
                axis = 1

            Nfft = int(next_fast_len(int(dataS.shape[axis])))
            fft_white = fft(white, Nfft, axis=axis) # return FFT

            ##
            self.data=fft_white
            self.Nfft=Nfft

            if freq_norm != 'no' and freqmin is not None:
                print('Constructing FFTData with whitening ...')
                self.whiten()  # whiten and return FFT
        else:
            self.std=None
            self.time=None
            self.data=None
            self.Nfft=None

    ##### method for whitening
    def whiten(self,freq_norm=None,smooth=None):
        """
        Whiten FFTData
        """
        if freq_norm is None: freq_norm=self.freq_norm
        if smooth is None: smooth=self.smooth_spec
        if self.freqmin is None:
            raise ValueError('freqmin has to be specified as an attribute in FFTData!')

        if self.freqmax is None:
            self.freqmax=0.499/self.dt
            print('freqmax not specified, use default as 0.499*samp_freq.')

        if self.data.ndim == 1:
            axis = 0
        elif self.data.ndim == 2:
            axis = 1

        Nfft = int(self.Nfft)

        Napod = 100
        freqVec = fftfreq(Nfft, d=self.dt)[:Nfft // 2]
        J = np.where((freqVec >= self.freqmin) & (freqVec <= self.freqmax))[0]
        low = J[0] - Napod
        if low <= 0:
            low = 1

        left = J[0]
        right = J[-1]
        high = J[-1] + Napod
        if high > Nfft/2:
            high = int(Nfft//2)

        FFTRawSign = self.data
        # Left tapering:
        if axis == 1:
            FFTRawSign[:,0:low] *= 0
            FFTRawSign[:,low:left] = np.cos(
                np.linspace(np.pi / 2., np.pi, left - low)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[:,low:left]))
            # Pass band:
            if freq_norm == 'phase_only':
                FFTRawSign[:,left:right] = np.exp(1j * np.angle(FFTRawSign[:,left:right]))
            elif freq_norm == 'rma':
                for ii in range(self.data.shape[0]):
                    tave = utils.moving_ave(np.abs(FFTRawSign[ii,left:right]),smooth)
                    FFTRawSign[ii,left:right] = FFTRawSign[ii,left:right]/tave
            # Right tapering:
            FFTRawSign[:,right:high] = np.cos(
                np.linspace(0., np.pi / 2., high - right)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[:,right:high]))
            FFTRawSign[:,high:Nfft//2] *= 0

            # Hermitian symmetry (because the input is real)
            FFTRawSign[:,-(Nfft//2)+1:] = np.flip(np.conj(FFTRawSign[:,1:(Nfft//2)]),axis=axis)
        else:
            FFTRawSign[0:low] *= 0
            FFTRawSign[low:left] = np.cos(
                np.linspace(np.pi / 2., np.pi, left - low)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[low:left]))
            # Pass band:
            if freq_norm == 'phase_only':
                FFTRawSign[left:right] = np.exp(1j * np.angle(FFTRawSign[left:right]))
            elif freq_norm == 'rma':
                tave = utils.moving_ave(np.abs(FFTRawSign[left:right]),smooth)
                FFTRawSign[left:right] = FFTRawSign[left:right]/tave
            # Right tapering:
            FFTRawSign[right:high] = np.cos(
                np.linspace(0., np.pi / 2., high - right)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[right:high]))
            FFTRawSign[high:Nfft//2] *= 0

            # Hermitian symmetry (because the input is real)
            FFTRawSign[-(Nfft//2)+1:] = FFTRawSign[1:(Nfft//2)].conjugate()[::-1]
        ##re-assign back to self.data.
        self.data=FFTRawSign

    def __str__(self):
        """
        Display key content of the object.
        """
        print("id           :   "+str(self.id))
        print("net          :   "+str(self.net))
        print("sta          :   "+str(self.sta))
        print("loc          :   "+str(self.loc))
        print("chan         :   "+str(self.chan))
        print("lon          :   "+str(self.lon))
        print("lat          :   "+str(self.lat))
        print("ele          :   "+str(self.ele))
        print("dt           :   "+str(self.dt))
        print("freqmin      :   "+str(self.freqmin))
        print("freqmax      :   "+str(self.freqmax))
        print("time_norm    :   "+self.time_norm)
        print("freq_norm    :   "+self.freq_norm)
        print("smooth       :   "+str(self.smooth))
        print("win_len      :   "+str(self.win_len))
        print("step         :   "+str(self.step))
        if self.std is not None:
            print("std          :   "+str(len(self.std)))
        else:
            print("std          :   none")
        if self.time is not None and len(self.time)>0:
            print("time         :   "+str(obspy.UTCDateTime(self.time[0]))+" to "+str(obspy.UTCDateTime(self.time[-1])))
        else:
            print("time         :   none")
        print("Nfft         :   "+str(self.Nfft))
        print("misc         :   "+str(self.misc))
        if self.data is not None and len(self.data)>0:
            print("data         :   "+str(self.data.shape))
        else:
            print("data         :   none")
        print("")
        return "<FFTData object>"

    def __add__(f1,f2):
        """
        Merge two FFTData objects with the same id. Only merge [time],[std],[data] attributes.
        """
        if f1.id != f2.id:
            raise ValueError('The object to be merged has a different ID (net.sta.loc.chan). Cannot merge!')

        time1=f1.time
        time2=f2.time
        std1=f1.std
        std2=f2.std
        data1=f1.data
        data2=f2.data

        time=np.concatenate((time1,time2))
        std=np.concatenate((std1,std2))
        data=np.concatenate((data1,data2),axis=0)

        return FFTData(win_len=f1.win_len,step=f1.step,id=f1.id,net=f1.net,
                        sta=f1.sta,loc=f1.loc,chan=f1.chan,lon=f1.lon,lat=f1.lat,ele=f1.ele,dt=f1.dt,
                        std=std,time=time,Nfft=f1.Nfft,data=data,freqmin=f1.freqmin,freqmax=f1.freqmax,
                        time_norm=f1.time_norm,freq_norm=f1.freq_norm,smooth=f1.smooth,
                        smooth_spec=f1.smooth_spec,misc=f1.misc,df=f1.df)
    def plot(self,xrange=None,time_format='%Y-%m-%dT%H',db=True,normalize=True,cmap='jet',figsize=(6,4),
            crange=None):
        """
        Plot amplitude spectrum of the FFTData.

        ====PARAMETERS====
        Default options:
        time_format='%Y-%m-%dT%H'
        db=True
        normalize=True
        cmap='jet'
        figsize=(6,4)
        crange: color range (default is None, automatically determined.)
        """
        ydata=self.time
        dt=self.dt
        Nfft2=int(self.Nfft/2)
        nwin=self.data.shape[0]
        if nwin>10:
            tick_inc = int(nwin/5)
        else:
            tick_inc = 2
        f=np.linspace(0,0.5/dt,Nfft2)
        if db:
            amp=10*np.log10(np.abs(self.data[:,:Nfft2]))
        else:
            amp=np.abs(self.data[:,:Nfft2])
        ampN=np.ndarray((amp.shape[0],amp.shape[1]))
        tmarks=[]
        for i in range(amp.shape[0]):
            if normalize: ampN[i,:]=amp[i,:]/np.max(np.abs(amp[i,:]))
            else: ampN[i,:]=amp[i,:]
            tmarks.append(obspy.UTCDateTime(ydata[i]).strftime(time_format))
        plt.figure(figsize=figsize,facecolor='w')
        ax=plt.subplot(111)
        plt.imshow(ampN,aspect='auto',extent=[f.min(),f.max(),ampN.shape[0],0],cmap=cmap)
        plt.xscale('log')
        if xrange is not None:
            plt.xlim(xrange)
        else:
            plt.xlim([f[1],f[-1]])
        plt.xlabel('frequency (Hz)', fontsize=12)
        plt.title('PSD for '+self.id,fontsize=13)
        ax.set_yticks(np.arange(0,nwin,tick_inc))
        ax.set_yticklabels(tmarks[0:nwin:tick_inc], fontsize=12)
        if crange is not None:plt.clim(crange)
        if normalize:
            if db:
                plt.colorbar(label='normalized amplitudes (dB)')
            else:
                plt.colorbar(label='normalized amplitudes')
        else:
            if db:
                plt.colorbar(label='amplitudes (dB)')
            else:
                plt.colorbar(label='amplitudes')
        plt.show()

class CorrData(object):
    """
    Object to store cross-correlation data. The idea of having a CorrData data type
    was originally designed by Tim Clements for SeisNoise.jl (https://github.com/tclements/SeisNoise.jl).
    The CorrData class in SeisGo differrs from that in SeisNoise by adding the internal methods
    for merging, plotting, and saving.
    ======= Attributes ======
    net=[None,None],sta=[None,None],loc=[None,None],chan=[None,None],lon=[None,None],
    lat=[None,None],ele=[None,None],cc_comp=None,
    lag=None,dt=None,dist=None,time=None,data=None,substack:bool=False
    cc_len,cc_step: cc parameters.
    az,baz: azimuth and back-azimuth of the two stations.
    side: A [Default]- both negative and positive sides, N - negative sides only, P - positive side only.
    misc=dict().

    misc is a dictionary that stores additional parameters.

    ======= Methods ======
    merge(): Merge with another object.
    to_sac(): convert and save to sac file, using obspy SACTrace object.
    plot(): simple plotting function to display the cross-correlation data.
    """
    def __init__(self,net=['',''],sta=['',''],loc=['',''],chan=['',''],\
                    lon=[0.0,0.0],lat=[0.0,0.0],ele=[0.0,0.0],cc_comp='',lag=0.0,\
                    dt=0.0,cc_len=None,cc_step=None,dist=0.0,az=0.0,baz=0.0,\
                    time=[],data=None,stack_method=None,substack:bool=False,side="A",misc=dict()):
        self.type='Correlation Data'
        self.id=net[0]+'.'+sta[0]+'.'+loc[0]+'.'+chan[0]+'_'+net[1]+'.'+sta[1]+'.'+loc[1]+'.'+chan[1]
        self.net=net
        self.sta=sta
        self.loc=loc
        self.chan=chan
        self.lon=lon
        self.lat=lat
        self.ele=ele
        if cc_comp is None:
            self.cc_comp=chan[0][-1]+chan[1][-1]
        else:
            self.cc_comp=cc_comp
        self.lag=lag
        self.dt=dt
        self.cc_len=cc_len
        self.cc_step=cc_step
        self.dist=dist
        self.az=az
        self.baz=baz
        self.time=time
        self.data=data
        self.stack_method=stack_method
        if side.lower() not in ["a","p","n"]:
            raise ValueError("Wrong side attribute value [%s], which has to be one of A, N, P."%(side))
        else:
            self.side=side
        self.substack=substack
        self.misc=misc

    def __str__(self):
        """
        Display key content of the object.
        """
        print("type     :   "+str(self.type))
        print("id       :   "+str(self.id))
        print("net      :   "+str(self.net))
        print("sta      :   "+str(self.sta))
        print("loc      :   "+str(self.loc))
        print("chan     :   "+str(self.chan))
        print("lon      :   "+str(self.lon))
        print("lat      :   "+str(self.lat))
        print("ele      :   "+str(self.ele))
        print("cc_comp  :   "+str(self.cc_comp))
        print("lag      :   "+str(self.lag))
        print("dt       :   "+str(self.dt))
        print("cc_len   :   "+str(self.cc_len))
        print("cc_step  :   "+str(self.cc_step))
        print("dist     :   "+str(self.dist))
        print("az       :   "+str(self.az))
        print("baz      :   "+str(self.baz))
        print("side     :   "+str(self.side))
        if self.time is not None:
            if self.substack:
                print("time     :   "+str(obspy.UTCDateTime(self.time[0]))+" to "+str(obspy.UTCDateTime(self.time[-1])))
            else:
                print("time     :   "+str(obspy.UTCDateTime(self.time)))
        else:
            print("time     :   none")
        print("substack :   "+str(self.substack))
        if self.stack_method is not None:
            print("stack_method:"+str(self.stack_method))
        if self.data is not None:
            print("data     :   "+str(self.data.shape))
            print(str(self.data))
        else:
            print("data     :   none")
        print("")

        return "<CorrData object>"

    def __add__(c1,c2):
        """
        Merge with another object for the same station pair. The idea is to merge multiple sets
        of CorrData at different time chunks. Therefore, this function will merge the following
        attributes only: <time>,<data>

        **Note: substack will be set to True after merging, regardless the value in the original object.**
        """
        #sanity check: stop merging and raise error if the two objects have different IDs.
        if c1.id != c2.id:
            print("IDs: "+c1.id+" + "+c2.id)
            raise ValueError('The object to be merged has a different ID (net.sta.loc.chan). Cannot merge!')
        if c1.side != c2.side:
            print("sides: "+c1.side+" + "+c2.side)
            raise ValueError('The object to be merged has a different side values. Cannot merge!')
        if not c1.substack:
            time1=np.reshape(c1.time,(1))
            data1=np.reshape(c1.data,(1,c1.data.shape[0]))
        else:
            time1=c1.time
            data1=c1.data
        if not c2.substack:
            time2=np.reshape(c2.time,(1))
            data2=np.reshape(c2.data,(1,c2.data.shape[0]))
        else:
            time2=c2.time
            data2=c2.data

        time=np.concatenate((time1,time2))
        data=np.concatenate((data1,data2),axis=0)

        cout=c1.copy(dataless=True)
        cout.time=time
        cout.substack=True
        cout.data=data

        return cout

    def merge(self,c):
        """
        Merge with another object for the same station pair. The idea is to merge multiple sets
        of CorrData at different time chunks. Therefore, this function will merge the following
        attributes only: <time>,<data>

        **Note: substack will be set to True after merging, regardless the value in the original object.**

        ===PARAMETERS===
        c: the other CorrData object to merge with.
        """
        #sanity check: stop merging and raise error if the two objects have different IDs.
        if self.id != c.id:
            print("IDs: "+self.id+" + "+c.id)
            raise ValueError('The object to be merged has a different ID (net.sta.loc.chan). Cannot merge!')
        if not self.substack:
            stime=np.reshape(self.time.copy(),(1))
            sdata=np.reshape(self.data.copy(),(1,self.data.shape[0]))
        else:
            stime=self.time.copy()
            sdata=self.data.copy()
        if not c.substack:
            ctime=np.reshape(c.time.copy(),(1))
            if np.ndim(c.data)==1:
                cdata=np.reshape(c.data.copy(),(1,c.data.shape[0]))
        else:
            ctime=c.time.copy()
            cdata=c.data.copy()

        self.time=np.concatenate((stime,ctime))
        try:
            self.data=np.concatenate((sdata,cdata),axis=0)
        except Exception as e:
            print("error in merging. skipped.")
            print(e)

        self.substack=True

    #subset method
    def subset(self,starttime=None,endtime=None,overwrite=False):
        """
        Subset the xcorr data by time.
        starttime: Start time in string, with the format of "2021_09_05_0_0_0" or an obspy UTCDateTime object.
        endtime: End time in the same format as the "starttime"
        overwrite: overwrite the data (default) or return the new subset CorrData object. Default: False.


        """
        if isinstance(starttime,str):
            sdatetime = obspy.UTCDateTime(starttime)
        else:
            sdatetime = starttime
        if isinstance(endtime,str):
            edatetime = obspy.UTCDateTime(endtime)
        else:
            edatetime = endtime
        if not self.substack:
            pass
        else:
            if sdatetime is None and edatetime is None:
                print("starttime and endtime are both None. Nothing to do with subset.")
            elif sdatetime is None:
                sdatetime=self.time[0]
            elif edatetime is None:
                edatetime=self.time[-1]
            idx=np.where((self.time >= sdatetime) & (self.time<= edatetime))[0]
            subtime=self.time[idx]
            subdata=self.data[idx,:]

            if overwrite:
                self.time=subtime
                self.data=subdata
            else:
                cdata=self.copy()
                cdata.time=subtime
                cdata.data=subdata
                return cdata

    #copy method.
    def copy(self,dataless=False):
        """
        This method returns a copy of the object.

        ====PARAMETER====
        dataless: only copies the metadata if True. Default is False.

        ====RETURN===
        cout: a copy of the object.
        """

        cout=CorrData(net=self.net,sta=self.sta,loc=self.loc,chan=self.chan,\
                        lon=self.lon,lat=self.lat,ele=self.ele,cc_comp=self.cc_comp,lag=self.lag,\
                        dt=self.dt,cc_len=self.cc_len,cc_step=self.cc_step,dist=self.dist,az=self.az,\
                        baz=self.baz,time=self.time.copy(),substack=self.substack,\
                        side=self.side,misc=self.misc)
        if not dataless:
            cout.data=self.data.copy()

        return cout

    def stack(self,win_len=None,method='linear',overwrite=True,ampcut=20,verbose=False,
                demean=True,stack_par=None):
        '''
        This function stacks the cross correlation data. It will overwrite the
        [data] attribute with the stacked trace, if overwrite is True. Substack will
        be set to False if win_len is None or there is only one trace left.

        PARAMETERS:
        ----------------------
        win_len: windown length in seconds for the substack, over which all the
                corrdata.data subset will be stacked. If None [default],it stacks
                all data into one single trace.
        method: stacking method, could be: linear, robust, pws, acf, or nroot.
        overwrite: if True, it replaces the data attribute in CorrData. Otherwise,
                    it returns the stacked data as a vector. Default: True.
        ampcut: used in QC, only stack traces that satisfy ampmax<ampcut*np.median(ampmax)).
                Default: 20. Use None to disable cutting by amplitudes.
        demean: demean before stacking. Default is True.
        stack_par: Defautl None. parameter dictionary to conduct stacking.

        RETURNS:
        -----------------------
        Only returns when overwrite is False.

        ds: stacked data.
        ts: timeflag of the substacks, only returns when win_len is NOT None.
        '''
        if isinstance(method,list):method=method[0]
        if win_len is None:
            if self.substack:
                if demean:
                    cc_temp = utils.demean(self.data)
                else:
                    cc_temp = self.data
                ampmax = np.max(cc_temp,axis=1)
                if ampcut is None:
                    tindx  = np.where( (ampmax<ampcut*np.median(ampmax)) & (ampmax>0))[0]
                else:
                    tindx  = np.where((np.abs(ampmax)>0))[0]
                nstacks=len(tindx)
                if nstacks >0:
                    cc_array = cc_temp[tindx,:]

                    # do stacking
                    ds = np.zeros((self.data.shape[1]),dtype=self.data.dtype)
                    if nstacks==1: ds=cc_array
                    else:
                        ds = stacking.seisstack(cc_array,method=method,par=stack_par)
                    if overwrite:
                        #overwrite the data attribute.
                        self.substack=False
                        self.time  = self.time[tindx[0]]
                        self.data=ds
                        self.stack_method=method
                    else:
                        return ds
                if verbose: print('stacked CorrData '+self.id+' with '+str(nstacks)+' traces.')
            else:
                print('substack is set to: False. No stacking applicable.')
                pass
        else: #### stacking over segments of time windows.
            if np.ndim(self.data)>1:
                if verbose: print('Stacking with given windown len %f'%(win_len))
                if self.time[-1] - self.time[0] >= win_len:
                    win=np.arange(self.time[0],self.time[-1]+0.5*win_len,win_len)  #all time chunks
                else:
                    win=np.array([self.time[0]])
                ts_temp=[]
                ds=np.ndarray((len(win),self.data.shape[1]),dtype=self.data.dtype)
                ds.fill(np.nan)
                ngood=[]
                for i in range(len(win)-1):
                    widx=np.where((self.time>=win[i]) & (self.time<win[i]+win_len))[0]
                    if len(widx) >0:
                        if demean:
                            cc0 = utils.demean(self.data[widx,:])
                        else:
                            cc0 = self.data[widx,:]
                        ampmax = np.max(cc0,axis=1)
                        if ampcut is None:
                            tindx  = np.where( (ampmax<ampcut*np.median(ampmax)) & (ampmax>0))[0]
                        else:
                            tindx  = np.where((np.abs(ampmax)>0))[0]
                        nstacks=len(tindx)
                        dstack = np.zeros((self.data.shape[1]),dtype=self.data.dtype)
                        if nstacks>0:
                            cc_array = cc0[tindx,:]

                            # do stacking
                            if nstacks==1: dstack=cc_array
                            else:
                                dstack = stacking.seisstack(cc_array,method=method,par=stack_par)

                            ds[i,:]=dstack
                            ngood.append(i)
                            ts_temp.append(win[i])

                #
                ts=np.array(ts_temp)
                ds=ds[ngood,:]

                if overwrite:
                    self.data=ds
                    self.time=ts
                    if len(ngood) ==1: self.substack = False
                    else: self.substack=True
                    self.stack_method=method
                else:
                    return ts,ds
            else:
                self.substack = False
                if overwrite: pass
                else:
                    return [],[]

    #split the negative and positive sides
    def split(self,taper=False,taper_frac=0.01,taper_maxlen=10,verbose=False):
        """
        This method splits the positive and negative sides of the <data> attribute in CorrData object.
        This method will assign the <side> attribute for each side.

        ========PARAMETERS===========
        taper: if True, applies taper to the data after splitting. Default False.
        taper_frac=0.01,taper_maxlen=10: taper parameters.

        ========RETURNS==============
        cout: the list of two CorrData objects.
        """
        cout=[]
        try: #older version didn't have "side" attribute.
            side=self.side
        except Exception as e:
            side="A"
        if side.lower()=="a":
            if verbose: print("Splitting negative and positive sides.")
        else:
            print("side attribute is %s. Only splits when side is A."%(self.side))
            return cout

        dt=self.dt
        #
        #initiate as zeros

        if self.substack:
            nhalfpoint=int(self.data.shape[1]/2)

            d_p=np.zeros((nhalfpoint+1),dtype=self.data.dtype)
            d_n=np.zeros((nhalfpoint+1),dtype=self.data.dtype)

            if taper:
                d_p=utils.taper(self.data[:,nhalfpoint:],
                                            fraction=taper_frac,maxlen=taper_maxlen)
                d_n=np.flip(utils.taper(self.data[:,:nhalfpoint+1],
                                            fraction=taper_frac,maxlen=taper_maxlen),axis=1)
            else:
                d_p=self.data[:,nhalfpoint:]
                d_n=np.flip(self.data[:,:nhalfpoint+1],axis=1)
        else:
            nhalfpoint=int(self.data.shape[0]/2)
            d_p=np.zeros((nhalfpoint+1),dtype=self.data.dtype)
            d_n=np.zeros((nhalfpoint+1),dtype=self.data.dtype)

            if taper:
                d_p=utils.taper(self.data[nhalfpoint:],
                                            fraction=taper_frac,maxlen=taper_maxlen)
                d_n=np.flip(utils.taper(self.data[:nhalfpoint+1],
                                            fraction=taper_frac,maxlen=taper_maxlen))
            else:
                d_p=self.data[nhalfpoint:]
                d_n=np.flip(self.data[:nhalfpoint+1])

        c_n=self.copy()
        c_n.side="N"
        c_n.data=d_n
        cout.append(c_n)

        c_p=self.copy()
        c_p.side="P"
        c_p.data=d_p
        cout.append(c_p)

        return cout
    #shaping
    def shaping(self,width,shift,wavelet='gaussian',overwrite=True,trim_end=False):
        """
        convolve with a shaping wavelet.

        ====PARAMETERS====
        width: if gaussian, sigma of the shaping wavelet. if ricker: distance
            between the two side lobes.
        shift: half length of the wavelet. This will determine the shift of
                the wavelet center.
        wavelet: type of wavelet. default gaussian. Options: gaussian or ricker.
        trim_end: trim the end of the result. otherwise, trim both start and end.
        """
        if wavelet.lower() not in helpers.wavelet_labels():
            raise ValueError(wavelet+" not supported.")
        dt=self.dt
        if wavelet.lower() == "gaussian":
            t,w=utils.gaussian(dt,width,shift)
        elif wavelet.lower() == "ricker":
            t,w=utils.ricker(dt,1/width,shift)
        else:
            raise ValueError(wavelet+" not supported.")
        nt=len(t)
        dout=np.ndarray(self.data.shape)

        if self.substack:
            npts=self.data.shape[1]
            for ii in range(self.data.shape[0]):
                dtemp=signal.convolve(self.data[ii],w)
                if trim_end:
                    dout[ii]=dtemp[:npts]
                else:
                    dout[ii]=dtemp[int(nt/2):int(nt/2)+npts]
        else:
            npts=self.data.shape[0]
            dtemp=signal.convolve(self.data,w)
            if trim_end:
                dout=dtemp[:npts]
            else:
                dout=dtemp[int(nt/2):int(nt/2)+npts]

        if not overwrite:
            cdataout=self.copy()
            cdataout.data=dout
            return cdataout
        else:
            self.data=dout
    #convert to EGF by taking the netagive time derivative of the noise correlation functions.
    def to_egf(self,taper_frac=0.01,taper_maxlen=10,verbose=False):
        """
        This function converts the CorrData correlaiton results to EGF by taking
        the netagive time derivative of the noise correlation functions.

        The positive and negative lags are converted seperatedly but merged afterward.

        =======PARAMETERS=========
        taper_frac: default 0.01. taper fraction when process the two sides seperatedly.
        taper_maxlen: default 10. taper maximum number of points.
        """
        if verbose: print("Converting to empirical Green's functions.")
        #type flag here
        egf_flag="Empirical Green's Functions"
        if self.type.lower() == egf_flag.lower():
            print("It seems the data is already EGFs. self.type="+self.type+". Skip without converting!")
            pass
        else:
            dt=self.dt
            try:
                side=self.side
            except Exception as e:
                side="A"
            #
            #initiate as zeros
            egf=np.zeros(self.data.shape,dtype=self.data.dtype)
            if self.substack:
                if side.lower()=="a":
                    nhalfpoint=int(self.data.shape[1]/2)
                    #positive side
                    egf[:,nhalfpoint:]=utils.taper(-1.0*np.gradient(self.data[:,nhalfpoint:],axis=1)/dt,
                                                    fraction=taper_frac,maxlen=taper_maxlen)
                    #negative side
                    egf[:,:nhalfpoint+1]=np.flip(utils.taper(-1.0*np.gradient(np.flip(self.data[:,:nhalfpoint+1],axis=1),
                                                    axis=1)/dt,fraction=taper_frac,maxlen=taper_maxlen),axis=1)
                    egf[:,[0,-1]]=0
                    egf[:,nhalfpoint]=np.mean(egf[:,nhalfpoint-1:nhalfpoint+1],axis=1)
                else:
                    egf=utils.taper(-1.0*np.gradient(self.data,axis=1)/dt,
                                                    fraction=taper_frac,maxlen=taper_maxlen)
            else:
                if side.lower()=="a":
                    nhalfpoint=int(self.data.shape[0]/2)
                    #positive side
                    egf[nhalfpoint:]=utils.taper(-1.0*np.gradient(self.data[nhalfpoint:])/dt,
                                                fraction=taper_frac,maxlen=taper_maxlen)
                    #negative side
                    egf[:nhalfpoint+1]=np.flip(utils.taper(-1.0*np.gradient(np.flip(self.data[:nhalfpoint+1]))/dt,
                                                fraction=taper_frac,maxlen=taper_maxlen))
                    egf[0,-1]=0
                    egf[nhalfpoint]=np.mean(egf[nhalfpoint-1:nhalfpoint+1])
                else:
                    egf=utils.taper(-1.0*np.gradient(self.data)/dt,
                                                fraction=taper_frac,maxlen=taper_maxlen)
            self.data=egf
            self.type=egf_flag

    #
    def filter(self,fmin=None,fmax=None,corners=4,zerophase=True):
        """
        Apply filter to CorrData.data. The parameters are same as for obspy.signal.filter filters.

        ==PARAMETERS==
        fmin, fmax: frequency range. if fmin is None, it will apply a lowpass filter.
                    if fmax is None, it will apply a highpass filter.
        corners: number of corners, default is 4.
        zerophase: default is True.
        """
        if fmin is None and fmax is None:
            raise ValueError("fmin and fmax CAN NOT all be None.")
        if self.substack:
            for i in range(self.data.shape[0]):
                if fmin is not None and fmax is not None:
                    self.data[i,:]=bandpass(self.data[i],fmin,fmax,1/self.dt,corners=corners, zerophase=zerophase)
                elif fmin is None:
                    self.data[i,:]=lowpass(self.data[i],fmax,1/self.dt,corners=corners, zerophase=zerophase)
                elif fmax is None:
                    self.data[i,:]=lhighpass(self.data[i],fmin,1/self.dt,corners=corners, zerophase=zerophase)
        else:
            if fmin is not None and fmax is not None:
                self.data=bandpass(self.data,fmin,fmax,1/self.dt,corners=corners, zerophase=zerophase)
            elif fmin is None:
                self.data=lowpass(self.data,fmax,1/self.dt,corners=corners, zerophase=zerophase)
            elif fmax is None:
                self.data=lhighpass(self.data,fmin,1/self.dt,corners=corners, zerophase=zerophase)
#
    def save(self,format,file=None,outdir=None,v=True):
        """
        Wrapper to save CorrData to file.
        format: required from user. "sac" or "asdf".
        file: filename. Will automatically determine one if None.
        outdir: output directory. Default None.
        v: verbose. Default True.
        """
        if format.lower() == "sac":
            self.to_sac(file=file,outdir=outdir,v=v)
        elif format.lower() == "asdf":
            self.to_asdf(file=file,outdir=outdir,v=v)
#
    def to_asdf(self,file=None,outdir=None,v=True):
        """
        Save CorrData object to asdf file.
        file: file name, which is required.
        """
        cc_comp = self.cc_comp
        # source-receiver pair
        netsta_pair = self.net[0]+'.'+self.sta[0]+'_'+\
                        self.net[1]+'.'+self.sta[1]
        chan_pair = self.chan[0]+'_'+self.chan[1]

        #save to asdf
        lonS,lonR = self.lon
        latS,latR = self.lat
        eleS,eleR = self.ele

        if "cc_method" in list(self.misc.keys()):
            cc_method = self.misc['cc_method']
        else:
            cc_method = ''
        if "dist_unit" in list(self.misc.keys()):
            dist_unit=self.misc['dist_unit']
        else:
            dist_unit=''
        parameters = {
            'net':self.net,
            'sta':self.sta,
            'chan':self.chan,
            'loc':self.loc,
            'dt':self.dt,
            'maxlag':np.float32(self.lag),
            'dist':np.float32(self.dist),
            'dist_unit':dist_unit,
            'azi':np.float32(self.az),
            'baz':np.float32(self.baz),
            'lonS':np.float32(lonS),
            'latS':np.float32(latS),
            'eleS':np.float32(eleS),
            'lonR':np.float32(lonR),
            'latR':np.float32(latR),
            'eleR':np.float32(eleR),
            'cc_method':cc_method,
            'cc_len':self.cc_len,
            'cc_step':self.cc_step,
            'time':self.time,
            'substack':self.substack,
            'comp':self.cc_comp,
            'type':self.type,
            'side':self.side,
            'stack_method':str(self.stack_method)}

        #check time size to avoid error. make sure it is not > 64kb
        #this is a temporary fix, though the ultimate fix will rely on HDF to lift the limit.
        if sys.getsizeof(self.time)/1024 > 64: #64k is the limit of HDF attribute.
            parameters['time']=np.float32(self.time-np.mean(self.time))
            parameters['time_mean']=np.mean(self.time)

        #
        if file is None:
            if not self.substack:
                corrtime=obspy.UTCDateTime(self.time)
            else:
                corrtime=obspy.UTCDateTime(self.time[0])
            file=str(corrtime).replace(':', '-')+'_'+self.id+'_'+self.cc_comp+'_'+self.side+'.h5'
            if outdir is None:
                outdir="."
            file=os.path.join(outdir,file)
        elif outdir is not None:
            file=os.path.join(outdir,file)

        fhead=os.path.split(file)[0]
        if len(fhead) >0 and not os.path.isdir(fhead): os.makedirs(fhead,exist_ok = True)

        with pyasdf.ASDFDataSet(file,mpi=False) as ccf_ds:
            ccf_ds.add_auxiliary_data(data=self.data, data_type=netsta_pair, path=chan_pair, parameters=parameters)
        if v: print('CorrData saved to: '+file)

    def to_sac(self,file=None,outdir=None,v=True):
        """
        Save CorrData object to sac file.

        ====PARAMETERS====
        outdir: output file directory. default is the current folder.
        file: specify file name, ONLY when there is only one trace. i.e., substack is False.
        v: verbose, default is True.
        """
        if outdir is None:
            outdir="."
        try:
            if not os.path.isdir(outdir):os.makedirs(outdir,exist_ok = True)
        except Exception as e:
            print(e)

        try:
            side=self.side
        except Exception as e:
            side="A"
        slon,rlon=self.lon
        slat,rlat=self.lat
        sele,rele=self.ele
        if side.lower()=="a":
            b=-self.lag
        else:
            b=0.0
        #
        network=self.net[1] #network for receiver.
        station=self.sta[1]
        evname=self.net[0]+"."+self.sta[0]
        comp = self.cc_comp
        if not self.substack:
            corrtime=obspy.UTCDateTime(self.time)
            nzyear=corrtime.year
            nzjday=corrtime.julday
            nzhour=corrtime.hour
            nzmin=corrtime.minute
            nzsec=corrtime.second
            nzmsec=corrtime.microsecond

            if file is None:
                file=str(corrtime).replace(':', '-')+'_'+self.id+'_'+self.cc_comp+'_'+side+'.sac'
            sac = SACTrace(nzyear=nzyear,nzjday=nzjday,nzhour=nzhour,nzmin=nzmin,nzsec=nzsec,nzmsec=nzmsec,
                           b=b,delta=self.dt,stla=rlat,stlo=rlon,stel=sele,evla=slat,evlo=slon,evdp=rele,
                           evel=rele,dist=self.dist,az=self.az,baz=self.baz,data=self.data,
                           kevnm=evname,knetwk=network,kstnm=station,kcmpnm=comp)

            sacfile  = os.path.join(outdir,file)
            sac.write(sacfile,byteorder='big')
            if v: print('saved sac to: '+sacfile)
        else:
            nwin=self.data.shape[0]
            for i in range(nwin):
                corrtime=obspy.UTCDateTime(self.time[i])
                nzyear=corrtime.year
                nzjday=corrtime.julday
                nzhour=corrtime.hour
                nzmin=corrtime.minute
                nzsec=corrtime.second
                nzmsec=corrtime.microsecond
                if file is None:
                    ofile=str(corrtime).replace(':', '-')+'_'+self.id+'_'+self.cc_comp+'_'+side+'.sac'
                    sacfile  = os.path.join(outdir,ofile)
                else:
                    sacfile  = os.path.join(outdir,file)
                sac = SACTrace(nzyear=nzyear,nzjday=nzjday,nzhour=nzhour,nzmin=nzmin,nzsec=nzsec,nzmsec=nzmsec,
                               b=b,delta=self.dt,stla=rlat,stlo=rlon,stel=sele,evla=slat,evlo=slon,evdp=rele,
                               evel=rele,dist=self.dist,az=self.az,baz=self.baz,data=self.data[i,:],
                               kevnm=evname,knetwk=network,kstnm=station,kcmpnm=comp)

                sac.write(sacfile,byteorder='big')
                if v: print('saved sac to: '+sacfile)

    def plot(self,freqmin=None,freqmax=None,lag=None,save=False,figdir=None,figsize=(10,8),
            figname=None,format='png',stack_method='linear',get_stack=False,stack_par=None,
            time_format='%Y-%m-%dT%H:%M:%S'):
        """
        Plotting method for CorrData. It is the same as seisgo.plotting.plot_corrdata(), with exactly the same arguments.
        Display the 2D matrix of the cross-correlation functions for a certain time-chunck.
        PARAMETERS:
        --------------------------
        freqmin: min frequency to be filtered
        freqmax: max frequency to be filtered
        lag: time ranges for display
        save: Save figure, default is False
        figdir: only applies when save is True.
        figsize: Matplotlib figsize, default is (10,8).
        format: figure format when saving. default png. Use pyplot's convention.
        stack_method: method to get the stack, default is 'linear'
        get_stack: returns the sacked trace if True. Default is False.
        stack_par: dictionary to store stacking parameters. Default None.
        time_format: format when labeling the individual traces. Default: '%Y-%m-%dT%H:%M:%S'
        """
        # open data for read
        if save:
            if figdir==None:print('no path selected! save figures in the default path')

        netstachan1 = self.net[0]+'.'+self.sta[0]+'.'+self.loc[0]+'.'+self.chan[0]
        netstachan2 = self.net[1]+'.'+self.sta[1]+'.'+self.loc[1]+'.'+self.chan[1]

        dt,maxlag,dist,ttime,substack = [self.dt,self.lag,self.dist,\
                                                self.time,self.substack]
        try:
            side=self.side
        except Exception as e:
            side="A"

        dreturn=[]
       # lags for display
        if not lag:lag=maxlag
        if lag>maxlag:raise ValueError('lag excceds maxlag!')
        lag0=np.min([1.0*lag,maxlag])

        # t is the time labels for plotting
        if lag>=5:
            tstep=int(int(lag)/5)
            if side.lower()=="a":
                t1=np.arange(-int(lag),0,step=tstep);t2=np.arange(0,int(lag+0.5*tstep),step=tstep)
                t=np.concatenate((t1,t2))
            else:
                t=np.arange(0,int(lag+0.5*tstep),step=tstep)
        else:
            tstep=lag/5
            if side.lower()=="a":
                t1=np.arange(-lag,0,step=tstep);t2=np.arange(0,lag+0.5*tstep,step=tstep)
                t=np.concatenate((t1,t2))
            else:
                t=np.arange(0,lag+0.5*tstep,step=tstep)

        if side.lower()=="a":
            indx1 = int((maxlag-lag0)/dt);indx2 = indx1+2*int(lag0/dt)+1
        else:
            indx1 = 0
            indx2 = int(lag0/dt)+1


        # cc matrix
        if substack:
            data = np.ndarray.copy(self.data[:,indx1:indx2])
            timestamp = np.empty(ttime.size,dtype='datetime64[s]')
            # print(data.shape)
            nwin = data.shape[0]
            amax = np.zeros(nwin,dtype=np.float32)
            if nwin==0:
                print('continue! no enough trace to plot!')
                return

            tmarks = []
            data_normalizd=np.zeros(data.shape)

            # load cc for each station-pair
            for ii in range(nwin):
                if freqmin is not None and freqmax is not None:
                    data[ii] = bandpass(data[ii],freqmin,freqmax,1/dt,corners=4, zerophase=True)
                data[ii] = utils.taper(data[ii]-np.mean(data[ii]),maxlen=10)
                amax[ii] = np.max(np.abs(data[ii]))
                data_normalizd[ii] = data[ii]/amax[ii]
                timestamp[ii] = obspy.UTCDateTime(ttime[ii])
                tmarks.append(obspy.UTCDateTime(ttime[ii]).strftime(time_format))

            dstack = stacking.seisstack(data,method=stack_method,par=stack_par)
            del data
    #         dstack_robust=stack.robust(data)[0]

            # plotting
            if nwin>10:
                tick_inc = int(nwin/5)
            else:
                tick_inc = 2

            fig = plt.figure(figsize=figsize,facecolor='w')
            ax = fig.add_subplot(6,1,(1,4))
            if side.lower()=="a":
                extent=[-lag0,lag0,nwin,0]
            else:
                extent=[0,lag0,nwin,0]
            ax.imshow(data_normalizd,cmap='seismic',extent=extent,aspect='auto')
            ax.plot((0,0),(nwin,0),'k-')
            if freqmin is not None and freqmax is not None:
                ax.set_title('%s-%s: dist=%5.2f km: %4.2f-%4.2f Hz: %s' % (netstachan1,netstachan2,
                                                                           dist,freqmin,freqmax,side))
            else:
                ax.set_title('%s-%s: dist=%5.2f km: unfiltered: %s' % (netstachan1,netstachan2,dist,side))
            ax.set_xlabel('time [s]')
            ax.set_xticks(t)
            ax.set_yticks(np.arange(0,nwin,step=tick_inc))
            ax.set_yticklabels(tmarks[0:nwin:tick_inc])
            if side.lower()=="a":
                ax.set_xlim([-lag,lag])
            else:
                ax.set_xlim([0,lag])
            ax.xaxis.set_ticks_position('bottom')

            ax1 = fig.add_subplot(6,1,(5,6))
            if freqmin is not None and freqmax is not None:
                ax1.set_title('stack at %4.2f-%4.2f Hz: %s'%(freqmin,freqmax,side))
            else:
                ax1.set_title('stack: unfiltered: %s'%(side))
            if side.lower()=="a":
                tstack=np.arange(-lag0,lag0+0.5*dt,dt)
            else:
                tstack=np.arange(0,lag0+0.5*dt,dt)
            if len(tstack)>len(dstack):tstack=tstack[:-2]
            ax1.plot(tstack,dstack,'b-',linewidth=1,label=stack_method)
    #         ax1.plot(tstack,dstack_robust,'r-',linewidth=1,label='robust')
            ax1.set_xlabel('time [s]')
            ax1.set_xticks(t)
            if side.lower()=="a":
                ax1.set_xlim([-lag,lag])
            else:
                ax1.set_xlim([0,lag])
            ylim=ax1.get_ylim()
            ax1.plot((0,0),ylim,'k-')

            ax1.set_ylim(ylim)
            ax1.legend(loc='upper right')
            ax1.grid()

            fig.tight_layout()

            dreturn=dstack

            tmark_figname=obspy.UTCDateTime(ttime[0]).strftime('%Y-%m-%dT%H-%M-%S')
        else: #only one trace available
            data = np.ndarray.copy(self.data[indx1:indx2])

            # load cc for each station-pair
            if freqmin is not None and freqmax is not None:
                data = bandpass(data,freqmin,freqmax,1/dt,corners=4, zerophase=True)
            data = utils.taper(data-np.mean(data),maxlen=10)
            amax = np.max(np.abs(data))
            data /= amax
            timestamp = obspy.UTCDateTime(ttime)
            tmarks=obspy.UTCDateTime(ttime).strftime(time_format)

            if side.lower()=="a":
                tx=np.arange(-lag0,lag0+0.5*dt,dt)
            else:
                tx=np.arange(0,lag0+0.5*dt,dt)
            if len(tx)>len(data):tx=tx[:-1]
            plt.figure(figsize=figsize,facecolor='w')
            ax=plt.gca()
            plt.plot(tx,data,'k-',linewidth=1)
            if freqmin is not None and freqmax is not None:
                plt.title('%s-%s: dist=%5.2f km: %4.2f-%4.2f Hz: %s: %s' % (netstachan1,netstachan2,
                                                                           dist,freqmin,freqmax,tmarks,side))
            else:
                plt.title('%s-%s: dist=%5.2f km: unfiltered: %s: %s' % (netstachan1,netstachan2,dist,tmarks,side))
            plt.xlabel('time [s]')
            plt.xticks(t)
            ylim=ax.get_ylim()
            plt.plot((0,0),ylim,'k-')

            plt.ylim(ylim)
            if side.lower()=="a":
                plt.xlim([-lag,lag])
            else:
                plt.xlim([0,lag])
            ax.grid()

            dreturn=data
            tstack=tx
            tmark_figname=obspy.UTCDateTime(ttime).strftime('%Y-%m-%dT%H-%M-%S')

        # save figure or just show
        if save:
            if figdir==None:figdir = '.'
            if not os.path.isdir(figdir):os.mkdir(figdir)
            if figname is None:
                outfname = figdir+\
                '/{0:s}_{1:s}_{2:s}-{3:s}Hz-{4:s}.{5:s}'.format(netstachan1,netstachan2,
                                                                 str(freqmin),str(freqmax),
                                                                 tmark_figname,format)
            else:
                outfname = figdir+'/'+figname
            plt.savefig(outfname, format=format, dpi=300)
            print('saved to: '+outfname)
            plt.close()
        else:
            plt.show()

        ##
        if get_stack:
            return tstack,dreturn

    ####
    def psd(self,cmap='jet',xrange=None,time_format='%Y-%m-%dT%H',normalize=True,figsize=(13,5)):
        """
        Plot the power specctral density of corrdata.data.

        =PARAMETERS=
        cmap: colormap, default is 'jet'
        time_format: format to show time marks, default is: '%Y-%m-%dT%H'
        normalize: whether normalize the PSD in plotting, default is True
        figsize: figure size, default: (13,5)
        """
        dt=self.dt
        if self.side.lower() == 'a':
            cdatan,cdatap=self.split()
            nplot=2
        elif self.side.lower() =='n':
            cdatan=self.copy()
            cdatap=None
            nplot=1
        else:
            cdatap=self.copy()
            cdatan=None
            nplot=1

        plt.figure(figsize=figsize,facecolor='w')
        cdata_all=[cdatan,cdatap]
        for ii,cdata in enumerate(cdata_all):
            if cdata is not None:
                if nplot==1:ax=plt.subplot(1,nplot,1)
                else:ax=plt.subplot(1,nplot,ii+1)

                data=cdata.data
                ydata=cdata.time
                nwin=data.shape[0]
                if nwin>10:
                    tick_inc = int(nwin/5)
                else:
                    tick_inc = 2
                f,p=utils.psd(data,1/dt)
                psdN=np.ndarray((p.shape[0],p.shape[1]))
                tmarks=[]
                for i in range(p.shape[0]):
                    if normalize: psdN[i,:]=p[i,:]/np.max(np.abs(p[i,:]))
                    else: psdN[i,:]=p[i,:]
                    tmarks.append(obspy.UTCDateTime(ydata[i]).strftime(time_format))

                plt.imshow(psdN,aspect='auto',extent=[f.min(),f.max(),psdN.shape[0],0],cmap=cmap)
                # plt.yscale('log')
                if xrange is None:plt.xlim([f[1],f[-1]])
                else:
                    plt.xlim(xrange)
                plt.xscale('log')
                ax.set_yticks(np.arange(0,nwin,step=tick_inc))
                ax.set_yticklabels(tmarks[0:nwin:tick_inc])
                if normalize: plt.colorbar(label='normalized PSD')
                else: plt.colorbar(label='PSD')
                plt.xlabel('frequency (Hz)')
                plt.title('PSD:'+cdata.id+':'+str(round(cdata.dist,2))+' km:'+cdata.side)

        plt.tight_layout()
        plt.show()
class DvvData(object):
    """
    Object to store dv/v (seismic velocity change) data. This object can be initiated by directly assigning
    values to each attributes OR by giving a CorrData object, in which case some attributes will be cloned
    from the CorrData object. In the latter case, you can still assign attributes that are unique to DvvData.

    ======= Attributes ======
    STATION INFORMATION:
    net=['',''],sta=['',''],loc=['',''],chan=['',''],
    lon=[0.0,0.0],lat=[0.0,0.0],ele=[0.0,0.0],cc_comp='',
    dist=0.0,az=0.0,baz=0.0: parameters specifying the stations.

    DVV PARAMETERS:
    method=None,window=None,dt=None,time=None,freq=None,misc=dict()

    misc is a dictionary that stores additional parameters.

    DVV DATA:
    cc1=None,cc2=None: cc1 and cc2 are the correlation coefficients arrays for negative measureemts
            and positive measurements, respectively. These are for the entire traces.
    maxcc1=None, maxcc2=None: maximum correlation coefficients when stretching for measuring dv/v.
    error1=None, error2=None: errors when measuring the dv/v.
    data1=None,data2=None: data1 is for dvv measurement using negative side correlation data.
            data2 is for the positive side.

    ======= Methods ======
    to_asdf(): save to asdf file.
    plot(): simple plotting function to display the cross-correlation data.
    """
    def __init__(self,corrdata=None,net=['',''],sta=['',''],loc=['',''],chan=['',''],\
                    lon=[0.0,0.0],lat=[0.0,0.0],ele=[0.0,0.0],cc_comp='',dist=0.0,dist_unit='',\
                    method=None,stack_method=None,window=None,dt=None,az=0.0,baz=0.0,time=None,freq=None,\
                    subfreq=True,normalize=False,cc1=None,cc2=None,maxcc1=None,maxcc2=None,\
                    error1=None,error2=None,data1=None,data2=None,misc=dict()):
        self.type='dv/v Data'
        if corrdata is None: #
            self.net=net
            self.sta=sta
            self.loc=loc
            self.chan=chan
            self.lon=lon
            self.lat=lat
            self.ele=ele
            if cc_comp is None:
                self.cc_comp=chan[0][-1]+chan[1][-1]
            else:
                self.cc_comp=cc_comp
            self.dt=dt
            self.dist=dist
            self.dist_unit=dist_unit
            self.az=az
            self.baz=baz
            self.time=time
            self.stack_method=stack_method
        else: ### use CorrData metadata when possible. only extract needed attributes.
            self.net=corrdata.net
            self.sta=corrdata.sta
            self.loc=corrdata.loc
            self.chan=corrdata.chan
            self.lon=corrdata.lon
            self.lat=corrdata.lat
            self.ele=corrdata.ele
            if cc_comp is None:
                self.cc_comp=corrdata.chan[0][-1]+corrdata.chan[1][-1]
            else:
                self.cc_comp=corrdata.cc_comp
            self.dt=corrdata.dt
            self.dist=corrdata.dist
            if "dist_unit" in list(corrdata.misc.keys()):
                self.dist_unit=corrdata.misc['dist_unit']
            else:
                self.dist_unit=dist_unit
            self.az=corrdata.az
            self.baz=corrdata.baz
            self.time=corrdata.time

        ##
        self.id=self.net[0]+'.'+self.sta[0]+'.'+self.loc[0]+'.'+self.chan[0]+'_'+\
            self.net[1]+'.'+self.sta[1]+'.'+self.loc[1]+'.'+self.chan[1]

        self.freq=freq
        self.subfreq=subfreq
        self.stack_method=stack_method
        self.method=method
        self.window=window
        self.normalize=normalize
        self.cc1=cc1
        self.cc2=cc2
        self.maxcc1=maxcc1
        self.maxcc2=maxcc2
        self.error1=error1
        self.error2=error2
        self.data1=data1
        self.data2=data2
        self.misc=misc

    def __str__(self):
        """
        Display key content of the object.
        """
        print("type     :   "+str(self.type))
        print("id       :   "+str(self.id))
        print("net      :   "+str(self.net))
        print("sta      :   "+str(self.sta))
        print("loc      :   "+str(self.loc))
        print("chan     :   "+str(self.chan))
        print("lon      :   "+str(self.lon))
        print("lat      :   "+str(self.lat))
        print("ele      :   "+str(self.ele))
        print("cc_comp  :   "+str(self.cc_comp))
        print("dt       :   "+str(self.dt))
        print("dist     :   "+str(self.dist))
        print("az       :   "+str(self.az))
        print("baz      :   "+str(self.baz))
        print("window   :   "+str(self.window))
        print("normalize:   "+str(self.normalize))
        print("method   :  "+str(self.method))
        print("stack    :  "+str(self.stack_method))
        print("misc     :   "+str(self.misc))
        print("freq     :   "+str(self.freq))
        print("subfreq  :   "+str(self.subfreq))

        try:
            print("time     :   "+str(obspy.UTCDateTime(self.time[0]))+" to "+str(obspy.UTCDateTime(self.time[-1])))
        except Exception as e:
            print("time     :   None")
        if self.cc1 is not None:
            print("cc1 [N]  :  "+str(self.cc2.shape))
        else:
            print("cc1 [N]:   none")
        if self.cc2 is not None:
            print("cc2 [P]  :  "+str(self.cc2.shape))
        else:
            print("cc2 [P]:   none")
        if self.maxcc1 is not None:
            print("maxcc1 [N]  :  "+str(self.maxcc1.shape))
        else:
            print("maxcc1 [N]:   none")
        if self.maxcc2 is not None:
            print("maxcc2 [P]  :  "+str(self.maxcc2.shape))
        else:
            print("maxcc2 [P]:   none")
        if self.error1 is not None:
            print("error1 [N]  :  "+str(self.error1.shape))
        else:
            print("error1 [N]:   none")
        if self.error2 is not None:
            print("error2 [P]  :  "+str(self.error2.shape))
        else:
            print("error2 [P]:   none")
        if self.data1 is not None:
            print("data1 [N]:   "+str(self.data1.shape))
        else:
            print("data1 [N]:   none")
        if self.data2 is not None:
            print("data2 [P]:   "+str(self.data2.shape))
        else:
            print("data2 [P]:   none")
        print("")

        return "<DvvData object>"

    ## method to get some info
    def get_info(self):
        """
        Get collective information.

        =====RETURNS====
        data: data matrix.
        label: data label.
        path: path label, particularly for heirachy file system.
        parameters: parameters for additional attributes
        """

        # source-receiver pair
        label = self.net[0]+'.'+self.sta[0]+'_'+\
                        self.net[1]+'.'+self.sta[1]
        path = self.chan[0]+'_'+self.chan[1]

        #save to asdf
        lonS,lonR = self.lon
        latS,latR = self.lat
        eleS,eleR = self.ele
        if self.data1 is not None and self.data2 is not None:
            side='A'
            odata=np.array([self.data1,self.data2])
        elif self.data1 is None:
            side='P'
            odata=self.data2
        else:
            side='N'
            odata=self.data1

        parameters = {'dt':self.dt,
            'dist':np.float32(self.dist),
            'dist_unit':self.dist_unit,
            'azi':np.float32(self.az),
            'baz':np.float32(self.baz),
            'lonS':np.float32(lonS),
            'latS':np.float32(latS),
            'eleS':np.float32(eleS),
            'lonR':np.float32(lonR),
            'latR':np.float32(latR),
            'eleR':np.float32(eleR),
            'window':np.float32(self.window),
            'stack_method':self.stack_method,
            'method':self.method,
            'normalize':self.normalize,
            'subfreq':self.subfreq,
            'time':self.time,
            'comp':self.cc_comp,
            'type':self.type,
            'freq':self.freq,
            'net':self.net,
            'sta':self.sta,
            'chan':self.chan,
            'side':side,
            'cc1':np.float32(self.cc1),
            'cc2':np.float32(self.cc2),
            'maxcc1':np.float32(self.maxcc1),
            'maxcc2':np.float32(self.maxcc2),
            'error1':np.float32(self.maxcc1),
            'error2':np.float32(self.maxcc2)}

        return odata,label,path,parameters


    def to_asdf(self,outdir='.',file=None,v=True):
        """
        Save DvvData object to asdf file.
        file: file name, default is like dvv_AK.CHN..BHE_AK.CHN..BHZ_EZ.h5.
        ======parameters======
        outdir: outdirectory, default is current folder
        file: file name, file extension will be added if not already there.
        v: verbose
        """
        if file is None:
            file="dvv_"+self.id+"_"+self.cc_comp+".h5"
        elif file[-2:] != "h5":
            file = file + ".h5"
        odata,netsta_pair,chan_pair,parameters=self.get_info()

        #check time size to avoid error. make sure it is not > 64kb
        #this is a temporary fix, though the ultimate fix will rely on HDF to lift the limit.
        time_temp=parameters['time']
        if sys.getsizeof(parameters['time'])/1024 > 64: #64k is the limit of HDF attribute.
            parameters['time']=np.float32(time_temp-np.mean(time_temp))
            parameters['time_mean']=np.mean(time_temp)

        with pyasdf.ASDFDataSet(outdir+'/'+file,mpi=False) as dvv_ds:
            dvv_ds.add_auxiliary_data(data=odata, data_type=netsta_pair, path=chan_pair, parameters=parameters)
        if v: print('DvvData saved to: '+outdir+'/'+file)
    #
    def to_pickle(self,outdir='.',file=None,v=True):
        """
        Save DvvData object to a pickle file.
        file: file name, default is like dvv_AK.CHN..BHE_AK.CHN..BHZ_EZ.pk.
        ======parameters======
        outdir: outdirectory, default is current folder
        file: file name, file extension will be added if not already there.
        v: verbose
        """
        overwrite=True #appending mode is not supported yet.
        if file is None:
            file="dvv_"+self.id+"_"+self.cc_comp+".pk"
        elif file[-2:] != "pk":
            file = file + ".pk"
        odata,netsta_pair,chan_pair,parameters=self.get_info()
        dvvdict={"data":odata,"label":netsta_pair,"path":chan_pair,"parameters":parameters}
        dvvoutdict={netsta_pair:{chan_pair:dvvdict}}
        if overwrite:
            mode="wb"
        else:
            mode="ab"
        with open(os.path.join(outdir,file),mode) as dvvf:
            pickle.dump(dvvoutdict,dvvf)
        if v: print('DvvData saved to: '+outdir+'/'+file)
    #
    def save(self,outdir='.',file=None,v=True,format=None):
        """
        Save DvvData object to a file. This is a wrapper of the saving functions for different file formats.
        file: file name, default is like dvv_AK.CHN..BHE_AK.CHN..BHZ_EZ.XX.
        ASDF file will end with "h5"
        Pickle file will end with "pk"

        ======parameters======
        outdir: outdirectory, default is current folder
        file: file name, file extension will be added if not already there.
        v: verbose
        format: "asdf" or "pickle". Default is "asdf", unless specified by the file extension.
        """
        format_all=["asdf","pickle"]
        fextlist=["h5","pk"]
        fend=file[-2:]
        if format is None:
            if fend.lower() in fextlist:
                if fend.lower() == "h5":
                    format = "asdf"
                elif fend.lower() == "pk":
                    format = "pickle"
            else:
                format = "asdf"
        elif format not in format_all:
            raise ValueError(format+" is not supported yet. Use one of: "+str(format_all))

        fext="h5"
        if format.lower() == "pickle":
            fext="pk"
        if file is None:
            file="dvv_"+self.id+"_"+self.cc_comp+"."+fext
        elif fend.lower() != fext:
            file = file + "."+fext

        # call corresponding saving functions
        if format.lower() == "asdf":
            self.to_asdf(outdir=outdir,file=file,v=v)
        elif format.lower() == "pickle":
            self.to_pickle(outdir=outdir,file=file,v=v)
        else:
            raise ValueError(format+" is not supported yet.")
    ##plot
    def plot(self,cc_min=None,figsize=(8,5),ylim=None,save=False,nxtick=None,\
            figdir='.',format='png',figname=None,smooth=None,yinc=1.0,ytick_precision=1,
            crange=None,side="a",errorbar=True,markersize=5):
        """
        Plot DvvData.

        cc_min: minimum max-correlation-coefficient in measuring dvv.
        figsize: figure size tuble
        ylim: y range for Display
        save: save figure. default False.
        figdir: directory to save figure. default is current directory.
        figname: figure name when save is True.
        smooth: box smooth options. should be a list of two elements. Defult None.
                Use same value for x and y if only one value is given.
        crange: colorbar range.
        yinc: y axis (frequency) increment.
        ytick_precision: precision of displaying frequency labels on y axis (default is 1)
        side: which side to plot. default is "a" for both negative and positive sides.
        errorbar: plot errobar or not for single frequency only. Default True.
        markersize: markersize for single frequency plots only. Default is 5.
        """
        nvdata=self.data1.copy()
        pvdata=self.data2.copy()
        if smooth is not None:
            if type(smooth) is not tuple and type(smooth) is not list:smooth=[smooth]
            if len(smooth)==1:smooth=[smooth[0],smooth[0]]
            nvdata=scipy.ndimage.filters.gaussian_filter(nvdata, smooth, mode='constant')
            pvdata=scipy.ndimage.filters.gaussian_filter(pvdata, smooth, mode='constant')
        if cc_min is None:
            cc_min=-1.0
        idx1=np.where((self.maxcc1<cc_min))
        nvdata[idx1]=np.nan

        idx2=np.where((self.maxcc2<cc_min))
        pvdata[idx2]=np.nan
        nwin=nvdata.shape[0]
        # tick inc for plotting
        if nxtick is None:
            nxtick = 5

        plt.figure(figsize=figsize, facecolor = 'white')
        # the cross-correlation coefficient

        #
        if self.subfreq: #multiple frequencies.
            # dv/v at each filtered frequency band
            xticks=np.int16(np.linspace(0,nwin-1,nxtick))
            xticklabel=[]
            for x in xticks:
                xticklabel.append(str(UTCDateTime(self.time[x]))[:10])
            period=1/self.freq
            if side.lower()=="a" or side.lower()=="n":
                dvv_array = nvdata.T
                yrange=[np.log2(period.min()),np.log2(period.max())]
                extent=(0,nwin,yrange[1],yrange[0])
                if side.lower()=="a":ax1 = plt.subplot(211)
                else:ax1 = plt.subplot(111)
                plt.imshow(dvv_array,cmap='jet_r',aspect='auto',extent=extent)

                plt.ylabel('frequency (Hz)',fontsize=12)
                ax1.set_xticks(xticks)
                ax1.set_xticklabels(xticklabel,fontsize=12)

                Yticks = 2 ** np.arange(np.log2(period.min()),
                                   np.log2(period.max()),yinc)
                ax1.set_yticks(np.log2(Yticks))
                ax1.set_yticklabels(np.round(1/Yticks,ytick_precision))
                if ylim is None:
                    plt.ylim(yrange)
                else:
                    plt.ylim(ylim)
                plt.yticks(fontsize=12)
                if crange is not None:plt.clim(crange)
                plt.colorbar(label='dv/v (%)')
                ax1.set_title('dv/v:'+self.id+':'+str(self.dist)+' km:negative:'+str(cc_min),fontsize=14)
                ax1.invert_yaxis()

            if side.lower()=="a" or side.lower()=="p":
                dvv_array = pvdata.T
                if side.lower()=="a":ax2 = plt.subplot(212)
                else:ax2 = plt.subplot(111)
                plt.imshow(dvv_array,cmap='jet_r',aspect='auto',extent=extent)
                plt.ylabel('frequency (Hz)',fontsize=12)
                ax2.set_xticks(xticks)
                ax2.set_xticklabels(xticklabel,fontsize=12)
                ax2.set_yticks(np.log2(Yticks))
                ax2.set_yticklabels(np.round(1/Yticks,ytick_precision))
                if ylim is None:
                    plt.ylim(yrange)
                else:
                    plt.ylim(ylim)
                plt.yticks(fontsize=12)
                if crange is not None:plt.clim(crange)
                plt.colorbar(label='dv/v (%)')
                ax2.set_title('dv/v:'+self.id+':'+str(self.dist)+' km:positive:'+str(cc_min),fontsize=14)
                ax2.invert_yaxis()
            plt.tight_layout()
        else: #only one measurement from one frequency
            xticks=np.linspace(np.min(self.time),np.max(self.time),nxtick)
            xticklabel=[]
            for x in xticks:
                xticklabel.append(str(UTCDateTime(x))[:10])
            xext=0.02*(np.max(self.time)-np.min(self.time))
            plt.hlines(0,np.min(self.time)-xext,np.max(self.time)+xext,colors='k')
            if side.lower()=="a" or side.lower()=="n":
                if errorbar:
                    plt.errorbar(self.time,nvdata,yerr=self.error1,fmt="o",markersize=markersize,
                                capsize=3,label="negative")
                else:
                    plt.plot(self.time,nvdata,".-",markersize=markersize,label="negative")
            if side.lower()=="a" or side.lower()=="p":
                if errorbar:
                    plt.errorbar(self.time,pvdata,yerr=self.error2,fmt="^",markersize=markersize,
                                capsize=3,label="positive")
                else:
                    plt.plot(self.time,pvdata,".-",markersize=markersize,label="positive")

            plt.ylabel('dv/v (%)',fontsize=12)
            plt.xlim([np.min(self.time)-xext,np.max(self.time)+xext])

            plt.xticks(xticks,labels=xticklabel,fontsize=12)
            plt.legend(fontsize=12)
            if ylim is not None:
                plt.ylim(ylim)
            plt.title('dv/v:'+self.id+':'+str(self.dist)+' km:'+side+':'+\
                        str(cc_min)+':'+str(np.min(self.freq))+"-"+str(np.max(self.freq))+" Hz",
                        fontsize=14)

        ###################
        ##### SAVING ######
        if save:
            if not os.path.isdir(figdir):os.mkdir(figdir)
            if figname is None: figname = 'dvv_'+self.id+'_'+self.cc_comp+'_'+side+\
                    '_'+str(cc_min)+'_'+str(np.min(self.freq))+"_"+str(np.max(self.freq))+"Hz"+'.'+format
            plt.savefig(figdir+'/'+figname, format=format, dpi=300, facecolor = 'white')
            plt.close()
        else:
            plt.show()

class Power(object):
    """
    Container for power spectra for each component, with any shape

    Attributes
    ----------
    c11 : :class:`~numpy.ndarray`
        Power spectral density for component 1 (any shape)
    c22 : :class:`~numpy.ndarray`
        Power spectral density for component 2 (any shape)
    cZZ : :class:`~numpy.ndarray`
        Power spectral density for component Z (any shape)
    cPP : :class:`~numpy.ndarray`
        Power spectral density for component P (any shape)
    """

    def __init__(spectra, c11=None, c22=None, cZZ=None, cPP=None, window=None,
                overlap=None,freq=None):
        spectra.c11 = c11
        spectra.c22 = c22
        spectra.cZZ = cZZ
        spectra.cPP = cPP
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq


class Cross(object):
    """
    Container for cross-power spectra for each component pairs, with any shape

    Attributes
    ----------
    c12 : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and 2 (any shape)
    c1Z : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and Z (any shape)
    c1P : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and P (any shape)
    c2Z : :class:`~numpy.ndarray`
        Cross-power spectral density for components 2 and Z (any shape)
    c2P : :class:`~numpy.ndarray`
        Cross-power spectral density for components 2 and P (any shape)
    cZP : :class:`~numpy.ndarray`
        Cross-power spectral density for components Z and P (any shape)
    """

    def __init__(spectra, c12=None, c1Z=None, c1P=None, c2Z=None, c2P=None,
                 cZP=None, window=None,overlap=None,freq=None):
        spectra.c12 = c12
        spectra.c1Z = c1Z
        spectra.c1P = c1P
        spectra.c2Z = c2Z
        spectra.c2P = c2P
        spectra.cZP = cZP
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq


class Rotation(object):
    """
    Container for rotated spectra, with any shape

    Attributes
    ----------
    cHH : :class:`~numpy.ndarray`
        Power spectral density for rotated horizontal component H (any shape)
    cHZ : :class:`~numpy.ndarray`
        Cross-power spectral density for components H and Z (any shape)
    cHP : :class:`~numpy.ndarray`
        Cross-power spectral density for components H and P (any shape)
    coh : :class:`~numpy.ndarray`
        Coherence between horizontal components
    ph : :class:`~numpy.ndarray`
        Phase of cross-power spectrum between horizontal components
    direc :: class: `~numpy.ndarray`
        All directions considered when computing the coh and ph.
    tilt : float
        Angle (azimuth) of tilt axis
    admt_value : : class :`~numpy.ndarray`
        Admittance between rotated horizontal at the tilt direction and vertical.
    coh_value : float
        Maximum coherence
    phase_value : float
        Phase at maximum coherence
    """

    def __init__(spectra, cHH=None, cHZ=None, cHP=None, coh=None, ph=None,direc=None,
                 tilt=None, admt_value=None,coh_value=None, phase_value=None,
                 window=None,overlap=None,freq=None):
        spectra.cHH = cHH
        spectra.cHZ = cHZ
        spectra.cHP = cHP
        spectra.coh = coh
        spectra.ph = ph
        spectra.direc = direc
        spectra.tilt = tilt
        spectra.admt_value = admt_value
        spectra.coh_value = coh_value
        spectra.phase_value = phase_value
        # spectra.angle = angle
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq
