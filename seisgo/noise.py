import os,sys,glob,time
import obspy
import scipy
import pycwt
import pyasdf
import datetime
import numpy as np
import pandas as pd
from obspy.signal.invsim import cosine_taper
from obspy.signal.regression import linear_regression
from obspy import Stream
from scipy.fftpack import fft,ifft,next_fast_len
from seisgo import stacking as stack
from seisgo.types import CorrData, FFTData
from seisgo import utils,helpers

#####
########################################################
################ CROSS-CORRELATE FUNCTIONS ##################
########################################################
def cc_memory(inc_hours,sps,nsta,ncomp,cc_len,cc_step):
    """
    Estimates the memory usage with given correlation parameters, assuming float 32.
    """
    nseg_chunk = int(np.floor((3600*inc_hours-cc_len)/cc_step))+1
    npts_chunk = int(nseg_chunk*cc_len*sps)
    memory_size = nsta*npts_chunk*4**ncomp/1024/1024/1024

    return memory_size

def compute_fft(trace,win_len,step,stainv=None,
                 freqmin=None,freqmax=None,time_norm='no',freq_norm='no',
                 smooth=20,smooth_spec=None,misc=dict(),taper_frac=0.05,df=None):
    """
    Call FFTData to build the object. This is an alternative of directly call FFTData().
    The motivation of this function is to provide an user interface to build FFTData object.
    """
    return FFTData(trace=trace,win_len=win_len,step=step,
                    stainv=stainv,freqmin=freqmin,freqmax=freqmax,time_norm=time_norm,
                    freq_norm=freq_norm,smooth=smooth,smooth_spec=smooth_spec,misc=misc,
                    taper_frac=taper_frac,df=df)
#assemble FFT with given asdf file name
def assemble_fft(sfile,win_len,step,correct_orientation=False,freqmin=None,freqmax=None,
                    time_norm='no',freq_norm='no',smooth=20,smooth_spec=20,
                    taper_frac=0.05,df=None,exclude_chan=[None],v=True):
    """
    Compute and assemble all FFTData from the raw data file "sfile".
    sfile: raw data file in ASDF format.
    win_len,step: segment length and sliding step in seconds.
    freqmin=None,freqmax=None: frequency range for spectrum whitening/smoothing.
    time_norm='no',freq_norm='no',smooth=20,smooth_spec=20: normalization choice and smoothing parameters.
    taper_frac=0.05: taper fraction when sliding through the data into segments.
    df=None: this is only used for FTN normalization.
    exclude_chan=[None]: channel to exclude.
    v=True: verbose option.
    """

    # retrive station information
    with pyasdf.ASDFDataSet(sfile,mpi=False,mode='r') as ds:    
        sta_list = ds.waveforms.list()
        nsta=len(sta_list)
        print('found %d stations in total'%nsta)
    
        fftdata_all=[]
        if nsta==0:
            print('no data in %s'%sfile);
            return fftdata_all
    
        # loop through all stations
        print('working on file: '+sfile.split('/')[-1])
    
        for ista in sta_list:
            # get station and inventory
            try:
                inv1 = ds.waveforms[ista]['StationXML']
                loc=[]
                for network in inv1:
                    for station in network:
                        for channel in station:
                            loc.append(channel.location_code)
            except Exception as e:
                print('abort! no stationxml for %s in file %s'%(ista,sfile))
                continue
            # get days information: works better than just list the tags
            all_tags = ds.waveforms[ista].get_waveform_tags()
            if len(all_tags)==0:continue
    
            #----loop through each stream----
            if len(all_tags)>3:
                print('Raw Data Error. Too many channels, check station metadata')
                continue
            else:
                #Set rotate and no-rotate flags to 0 for each station to avoid error
                #Do rotation of channels 1 or 2 to N or E
                rotate_flag=0
                no_rotate_flag=0
                channels=[]
                if correct_orientation==True:
                    print('Rotating 1/2 channels to E/N channels')
                    # Read channel info and decide if channel rotation is needed
                    for itag in all_tags:
                        if v:print("FFT for station %s and trace %s" % (ista,itag))
                        chan=itag.split('_')[0][-1]
                        loc_id=itag.split('_')[-1]
                        if chan=='1':
                            tr1=ds.waveforms[ista][itag][0]
                            if loc and loc[0] == '':
                                sta_name=ista+'.'+'.'+itag.split('_')[0].upper()
                            else:
                                sta_name=ista+'.'+loc_id+'.'+itag.split('_')[0].upper()
                            or1=inv1.get_orientation(sta_name)['azimuth']
                            rotate_flag+=1
                            print('Rotated channel 1 to N for %s' %(sta_name))
                        elif chan=='2':
                            tr2=ds.waveforms[ista][itag][0]
                            if loc and loc[0] == '':
                                sta_name=ista+'.'+'.'+itag.split('_')[0].upper()
                            else:
                                sta_name=ista+'.'+loc_id+'.'+itag.split('_')[0].upper()
                            or2=inv1.get_orientation(sta_name)['azimuth']
                            rotate_flag+=1
                            print('Rotated channel 2 to E for %s' %(sta_name))
                        else:
                            no_rotate_flag=1
                            channels.append(itag)
                            print('Channel not 1 or 2, no rotation needed')
                            pass
                    # Do channel rotation if rotate_flag==1
                    if rotate_flag==2:
                        orient=dict()
                        orient[ista]=(or1,or2,0)
                        # Correct any timestamp error if have
                        tr1_len=tr1.stats.npts
                        tr2_len=tr2.stats.npts
                        dt=1/tr1.stats.sampling_rate
                        # traces have the same length, no correction needed
                        if tr1_len==tr2_len:
                            trE,trN=utils.correct_orientations(tr1,tr2,orient)
                        # traces are not the same length
                        else:
                            tr1_start=tr1.stats.starttime
                            tr2_start=tr2.stats.starttime
                            print(tr1.stats.starttime)
                            print(tr2.stats.starttime)
                            t_error=tr1_start-tr2_start
                            # tr1 is longer (start time is earlier)
                            if t_error<0:
                                if abs(t_error)>dt/2 and abs(t_error)<dt:    # If time difference is greater than half dt and smaller than dt (closer to the next sampling point), zero pad at front
                                    tr2.data=np.insert(tr2.data,0,0)
                                elif abs(t_error)<dt/2:                      # Otherwise, zero pad at end
                                    tr2.data=np.append(tr2.data,0)
                                else:
                                    print('Time error is larger than sampling interval, check data')
                                # Update start and end time of the short trace using those of the longer trace
                                tr2.stats.starttime=tr1.stats.starttime
                            # tr2 is longer (start time is earlier)
                            else:
                                if abs(t_error)>dt/2 and abs(t_error)<dt:
                                    tr1.data=np.insert(tr1.data,0,0)
                                elif abs(t_error)<dt/2:
                                    tr1.data=np.append(tr1.data,0)
                                else:
                                    print('Time error is larger than sampling interval, check data')
                                tr1.stats.starttime=tr2.stats.starttime
                            print('Time error correction finished')
                               
                        trE,trN=utils.correct_orientations(tr1,tr2,orient)
                            
                        stE=Stream([trE])
                        stN=Stream([trN])
                        source=[stN,stE]
                        for itr in source:
                            comp = itr[0].stats.channel
                            if comp[-1] =='U': comp=comp.replace('U','Z')
                            
                            if comp in exclude_chan:
                                print(comp+" is in the exclude_chan list. Skip it!")
                                continue
                            fftdata=FFTData(itr,win_len,step,stainv=inv1,
                                            time_norm=time_norm,freq_norm=freq_norm,
                                            smooth=smooth,freqmin=freqmin,freqmax=freqmax,
                                            smooth_spec=smooth_spec,taper_frac=taper_frac,df=df)
                            if fftdata.data is not None:
                                fftdata_all.append(fftdata)
                    elif rotate_flag==1:
                        print('CONTINUE! Too less chennels for rotation, which requires 2 channels')
                        continue
                    # Skip channel rotation if rotate_flag==1
                    if no_rotate_flag==1:
                        source = []
                        for tag in channels:
                            print(tag,'was passed directly to fft')
                            source.append(ds.waveforms[ista][tag])
    
                        for itr in source:
                            comp = itr[0].stats.channel
                            if comp[-1] =='U': comp=comp.replace('U','Z')
                            
                            if comp in exclude_chan:
                                print(comp+" is in the exclude_chan list. Skip it!")
                                continue
                            fftdata=FFTData(itr,win_len,step,stainv=inv1,
                                            time_norm=time_norm,freq_norm=freq_norm,
                                            smooth=smooth,freqmin=freqmin,freqmax=freqmax,
                                            smooth_spec=smooth_spec,taper_frac=taper_frac,df=df)
                            if fftdata.data is not None:
                                fftdata_all.append(fftdata)
                
                else:
                    for itag in all_tags:
                        if v:print("FFT for station %s and trace %s" % (ista,itag))
                        # read waveform data
                        source = ds.waveforms[ista][itag]
                        if len(source)==0:continue
    
                        # channel info
                        comp = source[0].stats.channel
                        if comp[-1] =='U': comp=comp.replace('U','Z')
    
                        #exclude some channels in the exclude_chan list.
                        if comp in exclude_chan:
                            print(comp+" is in the exclude_chan list. Skip it!")
                            continue
    
                        fftdata=FFTData(source,win_len,step,stainv=inv1,
                                        time_norm=time_norm,freq_norm=freq_norm,
                                        smooth=smooth,freqmin=freqmin,freqmax=freqmax,
                                        smooth_spec=smooth_spec,taper_frac=taper_frac,df=df)
                        if fftdata.data is not None:
                            fftdata_all.append(fftdata)
####
    return fftdata_all

def smooth_source_spect(fft1,cc_method,sn):
    '''
    this function smoothes amplitude spectrum of the 2D spectral matrix. (used in S1)
    PARAMETERS:
    ---------------------
    fft1:    source spectrum matrix
    cc_method: correlaiton method, one of "xcorr", "deconv", "coherency"
    sn: number of samples in smoothng.

    RETURNS:
    ---------------------
    sfft1: complex numpy array with normalized spectrum
    '''
    smoothspect_N = sn #cc_para['smoothspect_N']

    N=fft1.shape[0]
    Nfft2=fft1.shape[1]
    fft1=fft1.reshape(fft1.size)
    if cc_method == 'deconv':

        #-----normalize single-station cc to z component-----
        temp = utils.moving_ave(np.abs(fft1),smoothspect_N)
        try:
            sfft1 = fft1/temp**2
        except Exception:
            raise ValueError('smoothed spectrum has zero values')

    elif cc_method == 'coherency':
        temp = utils.moving_ave(np.abs(fft1),smoothspect_N)
        try:
            sfft1 = fft1/temp
        except Exception:
            raise ValueError('smoothed spectrum has zero values')

    elif cc_method == 'xcorr':
        sfft1 = fft1

    else:
        raise ValueError('no correction correlation method is selected at L59')

    return sfft1.reshape(N,Nfft2)
#
def do_correlation(sfile,win_len,step,maxlag,cc_method='xcorr',acorr_only=False,
                    xcorr_only=False,substack=False,correct_orientation=False,substack_len=None,smoothspect_N=20,
                    maxstd=10,freqmin=None,freqmax=None,time_norm='no',freq_norm='no',
                    smooth_N=20,exclude_chan=[None],outdir='.',v=True,output_structure="raw"):
    """
    Wrapper for computing correlation functions. It includes two key steps: 1) compute and assemble
    the FFT of all data in the sfile, into a list of FFTData objects; 2) loop through the FFTData object
    list and do correlation (auto or xcorr) for each source-receiver pair.

    ===PARAMETERS===
    sfile: raw data file in ASDF format.
    win_len,step,maxlag,cc_method='xcorr': correlation parameters. cc_method: one of "xcorr", "deconv", "coherency"
    acorr_only=False: only compute autocorrelation when True.
    xcorr_only=False: Only compute cross-correlations when True.
    substack=False,substack_len=None: keep substack or not. If True, specify substack_len (in seconds.)
    smoothspect_N=20,smooth_N=20: smoothing parametes when rma is used for frequency and time domain, respectively.
    maxstd=10: drop data segments with std > this threshold.
    freqmin=None,freqmax=None: frequency range for frequency doman normalizaiton/smoothing.
    time_norm='no',freq_norm='no': normalization choices.
    exclude_chan=[None]: this is needed when some channels to be excluded
    outdir='.': path to save the output ASDF files.
    v=True: verbose flag
    output_structure="raw": output file structure. see `seisgo.helpers.xcorr_output_structure()` for available options..

    ====RETURNS====
    ndata: the number of station-component pairs in the sfile, that have been processed.
    """
    if win_len in [1,2,3]:
        print("!!!WARNING: you may call do_correlation() in the old way with the 2nd argument as the ncomp info.")
        print("         This may cause errors with arguments getting the wrong values. In this version and later,")
        print("         ncomp is deprecated. No change for other arguments. This warning will be removed in")
        print("         versions v0.7.x and later.")

    if acorr_only and xcorr_only:
        raise ValueError('acorr_only and xcorr_only CAN NOT all be True.')
    output_o,output_o_short=helpers.xcorr_output_structure()
    if output_structure not in output_o and output_structure not in output_o_short:
        raise ValueError(output_structure + " is not recoganized. must be one of "+str(output_o)+" or "+str(output_o_short))
    tname = sfile.split('/')[-1]
    tmpfile = os.path.join(outdir,tname.split('.')[0]+'.tmp')
    if not os.path.isdir(outdir):os.makedirs(outdir,exist_ok = True)
    #file to store CC results.
    outfile=os.path.join(outdir,tname)
    fhead,ftail=os.path.split(outfile)
    # check whether time chunk been processed or not
    if os.path.isfile(tmpfile):
        with open(tmpfile, 'r') as ftemp:
        #ftemp = open(tmpfile,'r')
            alines = ftemp.readlines()
            if len(alines) and alines[-1] == 'done':
                ftemp.close()
                return 0
            else:
                ftemp.close()
                os.remove(tmpfile)
                if os.path.isfile(outfile): os.remove(outfile)

    ftmp = open(tmpfile,'w')

    ##############compute FFT#############
    fftdata=assemble_fft(sfile,win_len,step,correct_orientation,freqmin=freqmin,freqmax=freqmax,
                    time_norm=time_norm,freq_norm=freq_norm,smooth=smooth_N,exclude_chan=exclude_chan)
    ndata=len(fftdata)

    #############PERFORM CROSS-CORRELATION##################
    if v: print(tname)
    iend=ndata
    for iiS in range(ndata):
        # get index right for auto/cross correlation
        istart=iiS;
        src=fftdata[iiS].net+"."+fftdata[iiS].sta
        # if acorr_only:iend=np.minimum(iiS+ncomp,ndata)
        # if xcorr_only:istart=np.minimum(iiS+ncomp,ndata)
        #-----------now loop III for each receiver B----------
        for iiR in range(istart,iend):
            # if v:print('receiver: %s %s' % (fftdata[iiR].net,fftdata[iiR].sta))
            rcv=fftdata[iiR].net+"."+fftdata[iiR].sta
            if (acorr_only and src==rcv) or (xcorr_only and src != rcv) or (not acorr_only and not xcorr_only):
                if fftdata[iiS].data is not None and fftdata[iiR].data is not None:
                    if v:print('receiver: %s %s' % (fftdata[iiR].net,fftdata[iiR].sta))
                    corrdata=correlate(fftdata[iiS],fftdata[iiR],maxlag,method=cc_method,substack=substack,
                                        smoothspect_N=smoothspect_N,substack_len=substack_len,
                                        maxstd=maxstd)

                    if corrdata.data is not None:
                        if output_structure.lower() == "raw" or output_structure.lower() == "r":
                            corrdata.to_asdf(file=outfile,v=v)
                        elif output_structure.lower() == "source" or output_structure.lower() == "s":
                            corrdata.to_asdf(file=os.path.join(fhead,corrdata.net[0]+'.'+corrdata.sta[0],ftail),v=v)
                        elif output_structure.lower() == "station-pair" or output_structure.lower() == "sp":
                            netsta_pair = corrdata.net[0]+'.'+corrdata.sta[0]+'_'+\
                                            corrdata.net[1]+'.'+corrdata.sta[1]
                            corrdata.to_asdf(file=os.path.join(fhead,netsta_pair,ftail),v=v)
                        elif output_structure.lower() == "station-component-pair" or output_structure.lower() == "scp":
                            netsta_pair = corrdata.net[0]+'.'+corrdata.sta[0]+'_'+\
                                            corrdata.net[1]+'.'+corrdata.sta[1]
                            chan_pair = corrdata.chan[0]+'_'+corrdata.chan[1]
                            corrdata.to_asdf(file=os.path.join(fhead,netsta_pair,chan_pair,ftail),v=v)
                        else:
                            raise ValueError(output_structure + " is not recoganized. must be one of "+\
                                    str(output_o)+" or "+str(output_o_short))

    # create a stamp to show time chunk being done
    ftmp.write('done')
    ftmp.close()

    return ndata

def correlate(fftdata1,fftdata2,maxlag,method='xcorr',substack=False,
                substack_len=None,smoothspect_N=20,maxstd=10,terror=0.01):
    '''
    this function does the cross-correlation in freq domain and has the option to keep sub-stacks of
    the cross-correlation if needed. it takes advantage of the linear relationship of ifft, so that
    stacking is performed in spectrum domain first to reduce the total number of ifft.

    PARAMETERS:
    ---------------------
    fftdata1: FFTData for the source station
    fftdata2: FFTData of the receiver station
    maxlag:  maximum lags to keep in the cross correlation
    method:  cross-correlation methods selected by the user
    terror: 0-1 fraction of timing error in searching for overlapping. The timing error =
                    terror*dt
    RETURNS:
    ---------------------
    corrdata: CorrData object of cross-correlation functions in time domain
    '''
    corrdata=CorrData()

    #check overlapping timestamps before any other processing
    #this step is required when there are gaps in the data.
    ind1,ind2=utils.check_overlap(fftdata1.time,fftdata2.time,error=terror*fftdata1.dt)
    if not len(ind1):
        print('no overlapped timestamps in the data.')
        return corrdata
    #
    dist,azi,baz = obspy.geodetics.base.gps2dist_azimuth(fftdata1.lat,fftdata1.lon,fftdata2.lat,fftdata2.lon)
    #---------- check the existence of earthquakes by std of the data.----------
    source_std = fftdata1.std[ind1]
    sou_ind = np.where((source_std<maxstd)&(source_std>0)&(np.isnan(source_std)==0))[0]
    if not len(sou_ind): return corrdata

    receiver_std = fftdata2.std[ind2]
    rec_ind = np.where((receiver_std<maxstd)&(receiver_std>0)&(np.isnan(receiver_std)==0))[0]
    if not len(rec_ind): return corrdata
    bb=np.intersect1d(sou_ind,rec_ind)
    if len(bb)==0:return corrdata

    bb_data1=[ind1[i] for i in bb]
    bb_data2=[ind2[i] for i in bb]

    #----load paramters----
    dt      = fftdata1.dt
    cc_len  = fftdata1.win_len
    cc_step = fftdata1.step
    if substack_len is None: substack_len=cc_len

    Nfft = fftdata1.Nfft
    Nfft2 = Nfft//2

    fft1=np.conj(fftdata1.data[bb_data1,:Nfft2]) #get the conjugate of fft1
    nwin  = fft1.shape[0]
    fft2=fftdata2.data[bb_data2,:Nfft2]

    timestamp=fftdata1.time[bb_data1]

    if method != "xcorr":
        fft1 = smooth_source_spect(fft1,method,smoothspect_N)
    #------convert all 2D arrays into 1D to speed up--------
    corr = np.zeros(nwin*Nfft2,dtype=np.complex64)
    corr = fft1.reshape(fft1.size,)*fft2.reshape(fft2.size,)

    if method == "coherency":
        temp = utils.moving_ave(np.abs(fft2.reshape(fft2.size,)),smoothspect_N)
        corr /= temp
    corr  = corr.reshape(nwin,Nfft2)

    if substack:
        if substack_len == cc_len:
            # choose to keep all fft data for a day
            s_corr = np.zeros(shape=(nwin,Nfft),dtype=np.float32)   # stacked correlation
            ampmax = np.zeros(nwin,dtype=np.float32)
            n_corr = np.zeros(nwin,dtype=np.int16)                  # number of correlations for each substack
            t_corr = timestamp                                        # timestamp
            crap   = np.zeros(Nfft,dtype=np.complex64)
            for i in range(nwin):
                n_corr[i]= 1
                crap[:Nfft2] = corr[i,:]
                # if dist > 0: # remove the mean in freq domain (spike at t=0). only for cross-station correlations.
                #     crap[:Nfft2] = crap[:Nfft2]-np.mean(crap[:Nfft2])
                crap[-(Nfft2)+1:] = np.flip(np.conj(crap[1:(Nfft2)]),axis=0)
                crap[0]=complex(0,0)
                s_corr[i,:] = np.real(np.fft.ifftshift(scipy.fftpack.ifft(crap, Nfft, axis=0)))

            # remove abnormal data
            ampmax = np.max(s_corr,axis=1)
            tindx  = np.where( (ampmax<20*np.median(ampmax)) & (ampmax>0))[0]
            s_corr = s_corr[tindx,:]
            t_corr = t_corr[tindx]
            n_corr = n_corr[tindx]

        else:
            # get time information
            Ttotal = timestamp[-1]-timestamp[0]             # total duration of what we have now
            tstart = timestamp[0]

            nstack = int(np.round(Ttotal/substack_len))
            ampmax = np.zeros(nstack,dtype=np.float32)
            s_corr = np.zeros(shape=(nstack,Nfft),dtype=np.float32)
            n_corr = np.zeros(nstack,dtype=int)
            t_corr = np.zeros(nstack,dtype=float)
            crap   = np.zeros(Nfft,dtype=np.complex64)

            for istack in range(nstack):
                # find the indexes of all of the windows that start or end within
                itime = np.where( (timestamp >= tstart) & (timestamp < tstart+substack_len) )[0]
                if len(itime)==0:tstart+=substack_len;continue

                crap[:Nfft2] = np.mean(corr[itime,:],axis=0)   # linear average of the correlation
                # if dist > 0: crap[:Nfft2] = crap[:Nfft2]-np.mean(crap[:Nfft2])   # remove the mean in freq domain (spike at t=0)
                crap[-(Nfft2)+1:]=np.flip(np.conj(crap[1:(Nfft2)]),axis=0)
                crap[0]=complex(0,0)
                s_corr[istack,:] = np.real(np.fft.ifftshift(scipy.fftpack.ifft(crap, Nfft, axis=0)))
                n_corr[istack] = len(itime)               # number of windows stacks
                t_corr[istack] = tstart                   # save the time stamps
                tstart += substack_len
                #print('correlation done and stacked at time %s' % str(t_corr[istack]))

            # remove abnormal data
            ampmax = np.max(s_corr,axis=1)
            tindx  = np.where( (ampmax<20*np.median(ampmax)) & (ampmax>0))[0]
            s_corr = s_corr[tindx,:]
            t_corr = t_corr[tindx]
            n_corr = n_corr[tindx]

    else:
        # average daily cross correlation functions
        ampmax = np.max(corr,axis=1)
        tindx  = np.where( (ampmax<20*np.median(ampmax)) & (ampmax>0))[0]
        n_corr = nwin
        s_corr = np.zeros(Nfft,dtype=np.float32)
        t_corr = timestamp[0]
        crap   = np.zeros(Nfft,dtype=np.complex64)
        crap[:Nfft2] = np.mean(corr[tindx],axis=0)
        # if dist > 0: crap[:Nfft2] = crap[:Nfft2]-np.mean(crap[:Nfft2],axis=0)
        crap[-(Nfft2)+1:]=np.flip(np.conj(crap[1:(Nfft2)]),axis=0)
        s_corr = np.real(np.fft.ifftshift(scipy.fftpack.ifft(crap, Nfft, axis=0)))

    # trim the CCFs in [-maxlag maxlag]
    t = np.arange(-Nfft2+1, Nfft2)*dt
    ind = np.where(np.abs(t) <= maxlag)[0]
    if s_corr.ndim==1:
        s_corr = s_corr[ind]
    elif s_corr.ndim==2:
        s_corr = s_corr[:,ind]

    ### call CorrData to build the object
    cc_comp= fftdata1.chan[-1]+fftdata2.chan[-1]

    corrdata=CorrData(net=[fftdata1.net,fftdata2.net],sta=[fftdata1.sta,fftdata2.sta],\
                    loc=[fftdata1.loc,fftdata2.loc],chan=[fftdata1.chan,fftdata2.chan],\
                    lon=[fftdata1.lon,fftdata2.lon],lat=[fftdata1.lat,fftdata2.lat],\
                    ele=[fftdata1.ele,fftdata2.ele],cc_comp=cc_comp,lag=maxlag,\
                    dt=fftdata1.dt,cc_len=cc_len,cc_step=cc_step,dist=dist/1000,az=azi,\
                    baz=baz,time=t_corr,data=s_corr,substack=substack,\
                    side="A",misc={"cc_method":method,"dist_unit":"km"})
    return corrdata

def do_stacking(ccfiles,pairlist=None,outdir='./STACK',method=['linear'],
                rotate=False,correctionfile=None,flag=False,keep_substack=False,
                to_egf=False):
    # source folder
    if pairlist is None:
        pairlist,netsta_all=get_stationpairs(ccfiles,False)
        if len(ccfiles)==0:
            raise IOError('Abort! no available CCF data for stacking')
        for s in netsta_all:
            tmp = os.path.join(outdir,s)
            if not os.path.isdir(tmp):os.mkdir(tmp)
    if isinstance(pairlist,str):pairlist=[pairlist]

    if not os.path.isdir(outdir):os.makedirs(outdir,exist_ok = True)
    if rotate:
        enz_system = ['EE','EN','EZ','NE','NN','NZ','ZE','ZN','ZZ']
        rtz_components = ['ZR','ZT','ZZ','RR','RT','RZ','TR','TT','TZ']
    for pair in pairlist:
        ttr   = pair.split('_')
        snet,ssta = ttr[0].split('.')
        rnet,rsta = ttr[1].split('.')
        idir  = ttr[0]

        # continue when file is done
        toutfn = os.path.join(outdir,idir+'/'+pair+'.tmp')
        if os.path.isfile(toutfn):continue
        if flag:print('assembling all corrdata ...')
        t0=time.time()
        corrdict_all=dict() #all components for the single station pair
        txtract=np.zeros(len(ccfiles),dtype=np.float32)
        tmerge=np.zeros(len(ccfiles),dtype=np.float32)
        tparameters=None
        for i,ifile in enumerate(ccfiles):
            # tt00=time.time()
            corrdict=extract_corrdata(ifile,pair=pair)
            # txtract[i]=time.time()-tt00
            if len(list(corrdict.keys()))>0:
                comp_list=list(corrdict[pair].keys())

                if len(comp_list)==0:
                    continue
                elif len(comp_list) >9:
                    print(comp_list)
                    raise ValueError('more than 9 cross-component exists for %s %s! please double check'%(ifile,pair))

                ### merge same component corrdata.
                # tt11=time.time()
                for c in comp_list:
                    #convert corrdata to empirical Green's functions by
                    #taking the negative time derivative. See types.CorrData.to_egf() for details.
                    if to_egf:
                        corrdict[pair][c].to_egf()

                    if tparameters is None:tparameters=corrdict[pair][c].misc
                    if c in list(corrdict_all.keys()):
                        corrdict_all[c].merge(corrdict[pair][c])
                    else:corrdict_all[c]=corrdict[pair][c]
                # tmerge[i]=time.time()-tt11
        #
        # if flag:print('extract time:'+str(np.sum(txtract)))
        # if flag:print('merge time:'+str(np.sum(tmerge)))
        t1=time.time()
        if flag:print('finished assembling in %6.2fs ...'%(t1-t0))
        #get length info from anyone of the corrdata, assuming all corrdata having the same length.
        cc_comp=list(corrdict_all.keys()) #final check on number of keys after merging all data.
        if len(cc_comp)==0:
            if flag:print('continue! no cross components for %s'%(pair))
            continue
        elif len(cc_comp)<9 and rotate:
            if flag:print('continue! not enough cross components for %s to do rotation'%(pair))
            continue
        elif len(cc_comp) >9:
            print(cc_comp)
            raise ValueError('more than 9 cross-component exists for %s! please double check'%(pair))

        #save data.
        outfn = pair+'.h5'
        if flag:print('ready to output to %s'%(outfn))

        t2=time.time()
        # loop through cross-component for stacking
        if isinstance(method,str):method=[method]
        tparameters['station_source']=ssta
        tparameters['station_receiver']=rsta
        if rotate: #need to order the components according to enz_system list.
            if corrdict_all[cc_comp[0]].substack:
                npts_segmt  = corrdict_all[cc_comp[0]].data.shape[1]
            else:
                npts_segmt  = corrdict_all[cc_comp[0]].data.shape[0]
            bigstack=np.zeros(shape=(9,npts_segmt),dtype=np.float32)
            if flag:print('applying stacking and rotation ...')
            stack_h5 = os.path.join(outdir,idir+'/'+outfn)
            ds=pyasdf.ASDFDataSet(stack_h5,mpi=False)
            #codes for ratation option.
            for m in method:
                data_type = 'Allstack_'+m
                bigstack=np.zeros(shape=(9,npts_segmt),dtype=np.float32)
                for icomp in range(9):
                    comp = enz_system[icomp]
                    indx = np.where(cc_comp==comp)[0]
                    # jump if there are not enough data
                    dstack,stamps_final=stacking(corrdict_all[cc_comp[indx[0]]],method=m)
                    bigstack[icomp]=dstack
                    tparameters['time']  = stamps_final[0]
                    ds.add_auxiliary_data(data=dstack, data_type=data_type, path=comp,
                                            parameters=tparameters)
                # start rotation
                if np.all(bigstack==0):continue

                bigstack_rotated = rotation(bigstack,tparameters,correctionfile,flag)

                # write to file
                data_type = 'Allstack_'+m
                for icomp2 in range(9):
                    rcomp  = rtz_components[icomp2]
                    if rcomp != 'ZZ':
                        ds.add_auxiliary_data(data=bigstack_rotated[icomp2], data_type=data_type,
                                                path=rcomp, parameters=tparameters)
            if keep_substack:
                for ic in cc_comp:
                    for ii in range(corrdict_all[ic].data.shape[0]):
                        tparameters2=tparameters
                        tparameters2['time']  = corrdict_all[ic].time[ii]
                        data_type = 'T'+str(int(corrdict_all[ic].time[ii]))
                        ds.add_auxiliary_data(data=corrdict_all[ic].data[ii], data_type=data_type,
                                            path=ic, parameters=tparameters2)

        else: #no need to care about the order of components.
            stack_h5 = os.path.join(outdir,idir+'/'+outfn)
            ds=pyasdf.ASDFDataSet(stack_h5,mpi=False)
            if flag:print('applying stacking ...')
            for ic in cc_comp:
                # write stacked data into ASDF file
                dstack,stamps_final=stacking(corrdict_all[ic],method=method)
                tparameters['time']  = stamps_final[0]
                for i in range(len(method)):
                    m=method[i]
                    ds.add_auxiliary_data(data=dstack[i,:], data_type='Allstack_'+m, path=ic,
                                            parameters=tparameters)

                if keep_substack:
                    for ii in range(corrdict_all[ic].data.shape[0]):
                        tparameters2=tparameters
                        tparameters2['time']  = corrdict_all[ic].time[ii]
                        data_type = 'T'+str(int(corrdict_all[ic].time[ii]))
                        ds.add_auxiliary_data(data=corrdict_all[ic].data[ii], data_type=data_type,
                                            path=ic, parameters=tparameters2)
        #
        if flag: print('stacking and saving took %6.2fs'%(time.time()-t2))
        # write file stamps
        ftmp = open(toutfn,'w');ftmp.write('done');ftmp.close()

        del corrdict_all

####
def stacking(corrdata,method='linear',par=None):
    '''
    this function stacks the cross correlation data

    PARAMETERS:
    ----------------------
    corrdata: CorrData object.
    method: stacking method, could be: linear, robust, pws, acf, or nroot.
    par: stacking parameters in a dictionary. See stacking.seisstack() for details.

    RETURNS:
    ----------------------
    dstack: 1D matrix of stacked cross-correlation functions over all the segments
    cc_time: timestamps of the traces for the stack
    '''
    if isinstance(method,str):method=[method]
    # remove abnormal data
    if corrdata.data.ndim==1:
        cc_time  = [corrdata.time]

        # do stacking
        dstack = np.zeros((len(method),corrdata.data.shape[0]),dtype=np.float32)
        for i in range(len(method)):
            m =method[i]
            dstack[i,:]=corrdata.data[:]
    else:
        ampmax = np.max(corrdata.data,axis=1)
        tindx  = np.where( (ampmax<20*np.median(ampmax)) & (ampmax>0))[0]
        nstacks=len(tindx)
        dstack=[]
        cc_time=[]
        if nstacks >0:
            # remove ones with bad amplitude
            cc_array = corrdata.data[tindx,:]
            cc_time  = corrdata.time[tindx]

            # do stacking
            dstack = np.zeros((len(method),corrdata.data.shape[1]),dtype=np.float32)
            for i in range(len(method)):
                m =method[i]
                if nstacks==1: dstack[i,:]=cc_array
                else:
                    dstack[i,:] = stack.seisstack(cc_array,method=method,par=par)

    # good to return
    return dstack,cc_time

def rotation(bigstack,parameters,locs,flag):
    '''
    this function transfers the Green's tensor from a E-N-Z system into a R-T-Z one

    PARAMETERS:
    -------------------
    bigstack:   9 component Green's tensor in E-N-Z system
    parameters: dict containing all parameters saved in ASDF file
    locs:       dict containing station angle info for correction purpose
    RETURNS:
    -------------------
    tcorr: 9 component Green's tensor in R-T-Z system
    '''
    # load parameter dic
    pi = np.pi
    azi = parameters['azi']
    baz = parameters['baz']
    ncomp,npts = bigstack.shape
    if ncomp<9:
        print('crap did not get enough components')
        tcorr=[]
        return tcorr
    staS  = parameters['station_source']
    staR  = parameters['station_receiver']

    if locs is not None:
        sta_list = list(locs['station'])
        angles   = list(locs['angle'])
        # get station info from the name of ASDF file
        ind   = sta_list.index(staS)
        acorr = angles[ind]
        ind   = sta_list.index(staR)
        bcorr = angles[ind]

        #---angles to be corrected----
        cosa = np.cos((azi+acorr)*pi/180)
        sina = np.sin((azi+acorr)*pi/180)
        cosb = np.cos((baz+bcorr)*pi/180)
        sinb = np.sin((baz+bcorr)*pi/180)
    else:
        cosa = np.cos(azi*pi/180)
        sina = np.sin(azi*pi/180)
        cosb = np.cos(baz*pi/180)
        sinb = np.sin(baz*pi/180)

    # rtz_components = ['ZR','ZT','ZZ','RR','RT','RZ','TR','TT','TZ']
    tcorr = np.zeros(shape=(9,npts),dtype=np.float32)
    tcorr[0] = -cosb*bigstack[7]-sinb*bigstack[6]
    tcorr[1] = sinb*bigstack[7]-cosb*bigstack[6]
    tcorr[2] = bigstack[8]
    tcorr[3] = -cosa*cosb*bigstack[4]-cosa*sinb*bigstack[3]-sina*cosb*bigstack[1]-sina*sinb*bigstack[0]
    tcorr[4] = cosa*sinb*bigstack[4]-cosa*cosb*bigstack[3]+sina*sinb*bigstack[1]-sina*cosb*bigstack[0]
    tcorr[5] = cosa*bigstack[5]+sina*bigstack[2]
    tcorr[6] = sina*cosb*bigstack[4]+sina*sinb*bigstack[3]-cosa*cosb*bigstack[1]-cosa*sinb*bigstack[0]
    tcorr[7] = -sina*sinb*bigstack[4]+sina*cosb*bigstack[3]+cosa*sinb*bigstack[1]-cosa*cosb*bigstack[0]
    tcorr[8] = -sina*bigstack[5]+cosa*bigstack[2]

    return tcorr

###
def merge_pairs(ccfiles,pairlist=None,outdir='./MERGED_PAIRS',verbose=False,to_egf=False,
            stack=False,stack_method='linear',stack_win_len=None,split=False,taper=True,
            taper_frac=0.01,taper_maxlen=10,ignore_channel_type=False):
    """
    This is a wrapper function that merges all data for the same station pair
    to a single CorrData object. It calls CorrData.merge() to assemble all CorrData.

    PARAMETERS
    ----------------------
    ccfiles: a list of correlation functions in ASDF format, saved to *.h5 file.
    pairlist: a list of station pairs to merge. If None (default), it will merge all
            station pairs.
    outdir: directory to save the data. Defautl is ./MERGED_PAIRS.
    verbose: verbose flag. Default is False.
    to_egf: whether to convert the data to empirical Green's functions (EGF) before
            saving. Default is False.
    stack: whether to stack all merged data before saving. Default: False.
    stack_method: when stack is True, this is the method for stacking.
    stack_win_len: window length in seconds for stacking, only used when stack is True.
            When stack_win_len is not None, the stacking will be done over the specified
            windown lengths, instead of the entire data set.
    """
    # source folder
    if pairlist is None:
        pairlist,netsta_all=get_stationpairs(ccfiles,False)
        if len(ccfiles)==0:
            raise IOError('Abort! no available CCF data for merging')
        for s in netsta_all:
            tmp = os.path.join(outdir,s)
            if not os.path.isdir(tmp):os.mkdir(tmp)
    if isinstance(pairlist,str):pairlist=[pairlist]

    if not os.path.isdir(outdir):os.makedirs(outdir,exist_ok = True)

    for pair in pairlist:
        ttr   = pair.split('_')
        snet,ssta = ttr[0].split('.')
        rnet,rsta = ttr[1].split('.')
        idir  = ttr[0]

        # continue when file is done
        ioutdir=os.path.join(outdir,idir)
        if not os.path.isdir(ioutdir):os.makedirs(ioutdir,exist_ok = True)

        if verbose:print('assembling all corrdata for pair ['+pair+'] ...')
        t0=time.time()
        corrdict_all=dict() #all components for the single station pair

        for ifile in ccfiles:
            # tt00=time.time()
            corrdict=extract_corrdata(ifile,pair=pair)
            # txtract[i]=time.time()-tt00
            if len(list(corrdict.keys()))>0:
                comp_list=list(corrdict[pair].keys())

                if len(comp_list)==0:
                    continue
                ### merge same component corrdata.
                # tt11=time.time()
                for c in comp_list:
                    if c in list(corrdict_all.keys()):
                        corrdict_all[c].merge(corrdict[pair][c],ignore_channel_type=ignore_channel_type)
                    else:corrdict_all[c]=corrdict[pair][c]
            del corrdict
                # tmerge[i]=time.time()-tt11

        t1=time.time()
        if verbose:print('finished assembling in %6.2fs ...'%(t1-t0))
        #get length info from anyone of the corrdata, assuming all corrdata having the same length.
        cc_comp=list(corrdict_all.keys()) #final check on number of keys after merging all data.
        if len(cc_comp)==0:
            if verbose:print('continue! no cross components for %s'%(pair))
            continue

        #save data.
        outfn = pair+'.h5'
        
        merged_h5 = os.path.join(ioutdir,outfn)
        if split:
            file_n=os.path.join(ioutdir,pair+'_N.h5')
            file_p=os.path.join(ioutdir,pair+'_P.h5')
        for ic in cc_comp:
            #save components.
            #convert corrdata to empirical Green's functions by
            #taking the negative time derivative. See types.CorrData.to_egf() for details.
            if stack:
                corrdict_all[ic].stack(method=stack_method,win_len=stack_win_len,overwrite=True)
            if to_egf:
                try:
                    corrdict_all[ic].to_egf()
                except Exception as e:
                    print(e)
            if split:
                n,p=corrdict_all[ic].split(taper=taper,taper_frac=taper_frac,
                                taper_maxlen=taper_maxlen,verbose=verbose)
                if verbose:print('save to %s and %s'%(file_n,file_p))
                n.to_asdf(file=file_n)
                p.to_asdf(file=file_p)
            else:
                if verbose:print('save to %s and %s'%(merged_h5,merged_h5))
                corrdict_all[ic].to_asdf(file=merged_h5)
        del corrdict_all
###
def split_sides(cfile,outdir='./PAIRS_SPLIT',taper=True,taper_frac=0.01,taper_maxlen=10,verbose=False):
    """
    This is a wrapper of CorrData.split() to seperate negative and positive sides.


    ====PARAMETERS====
    cfile: ASDF file containing xcorrdata.
    outdir: root directory for output data. Default '/PAIRS_SPLIT'.
    taper=True,taper_frac=0.01,taper_maxlen=10: all split() parameters. Note that we turn on taper by default.
    verbose: default False.
    """
    fext="h5" #reserve for future development with other file formats.
    cdataall = extract_corrdata(cfile)
    ofilebase=os.path.split(cfile)[1].replace('.'+fext,'')
    ofile_n=os.path.join(outdir,ofilebase+"_n."+fext)
    ofile_p=os.path.join(outdir,ofilebase+"_p."+fext)

    pairall=list(cdataall.keys())
    for pair in pairall:
        ccomp_all=list(cdataall[pair].keys())
        for c in ccomp_all:
            if cdataall[pair][c].side.lower() == "a":
                if cdataall[pair][c].data.size: # only process non-empty data.
                    n,p=cdataall[pair][c].split(taper=taper,taper_frac=taper_frac,
                                    taper_maxlen=taper_maxlen,verbose=verbose)
                    n.to_asdf(file=ofile_n)
                    p.to_asdf(file=ofile_p)
                else:
                    print("data attribute is empty. skipped.")
            else:
                raise ValueError("Only splits when side is A. We got side as %s for %s and %s"%(cdataall[pair][c].side,pair,c))

###
def merge_chunks(ccfiles,outdir='./MERGED_CHUNKS',verbose=False,to_egf=False,
            stack=False,stack_method='linear',stack_win_len=None):
    """
    This is a wrapper function that merges all data in the given list of correlation files.
    It calls CorrData.merge() to assemble all CorrData for the same station and component pairs.
    The functionality is similar with noise.merge_pairs(). This is particularly useful when the
    number of chunks is too large to be handled. At the same time, it provides the option to further
    reduce the data size by stacking. Please note that the stacking here works for the given
    list of files.

    PARAMETERS
    ----------------------
    ccfiles: a list of correlation functions in ASDF format, saved to *.h5 file.
    outdir: directory to save the data. Defautl is ./MERGED_PAIRS.
    verbose: verbose flag. Default is False.
    to_egf: whether to convert the data to empirical Green's functions (EGF) before
            saving. Default is False.
    stack: whether to stack all merged data before saving. Default: False.
    stack_method: when stack is True, this is the method for stacking.
    stack_win_len: window length in seconds for stacking, only used when stack is True.
            When stack_win_len is not None, the stacking will be done over the specified
            windown lengths, instead of the entire data set. The function stacks all data if "stack_win_len"
            > the time duration of the whole list of correlation files.
    """
    pairs_all,netsta,trange=get_stationpairs(ccfiles,getcclist=False,gettimerange=True)
    ts,te=trange
    outfile = os.path.join(outdir,str(obspy.UTCDateTime(ts)).replace(':', '-') + \
                                'T' + str(obspy.UTCDateTime(te)).replace(':', '-') + '.h5')
    for p in pairs_all:
        corrdict_all=dict()
        for f in ccfiles:
            # print("---> "+ifile)
            corrdict=extract_corrdata(f,pair=p)
            # txtract[i]=time.time()-tt00
            if len(list(corrdict.keys()))>0:
                comp_list=list(corrdict[p].keys())

                if len(comp_list)==0:
                    continue
                ### merge same pair and component corrdata.
                # tt11=time.time()
                if p not in list(corrdict_all.keys()):
                    corrdict_all[p]=corrdict[p]
                for c in comp_list:
                    if c in list(corrdict_all[p].keys()):
                        corrdict_all[p][c].merge(corrdict[p][c])
                    else:
                        corrdict_all[p][c]=corrdict[p][c]

            del corrdict
        #
        if p in list(corrdict_all.keys()):
            comp_list=list(corrdict_all[p].keys())
            if len(comp_list)>0:
                for c in comp_list:
                    if corrdict_all[p][c].data is not None:
                        if stack:
                            corrdict_all[p][c].stack(method=stack_method,win_len=stack_win_len)
                        if to_egf:
                            corrdict_all[p][c].to_egf()
                        corrdict_all[p][c].to_asdf(file=outfile,v=False)
    del corrdict_all

##
def reorganize_corrfile(ccfile,output_structure,pairlist=None,outdir='./CCF_OUT',v=False):
    """
    This function reorganize time chunk xcorr files by seperating station pairs.
    Each station pair will be in a seperate folder, with all time chunks. This is
    designed to reduce the computational needs when merging station pairs for later
    processes.

    ===== parameters ====
    ccfile: cross correlaiton file in ASDF format.
    output_structure: structure to organize the output files. see `seisgo.helpers.xcorr_output_structure()`
                    for available options.
    pairlist: list of station pairs to convert.
    outdir: root directory to save the output. Default: ./CCF_OUT
    v: False
    """
    output_o,output_o_short=helpers.xcorr_output_structure()
    if output_structure not in output_o and output_structure not in output_o_short:
        raise ValueError(output_structure + " is not recoganized. must be one of "+str(output_o)+" or "+str(output_o_short))

    corrdict=extract_corrdata(ccfile,pair=pairlist)

    pairs_all=list(corrdict.keys())

    fnamebase=os.path.split(ccfile)[-1]
    for p in pairs_all:
        cc_all=list(corrdict[p].keys()) #all component for this pair,
        #
        for c in cc_all:
            if output_structure.lower() == "raw" or output_structure.lower() == "r":
                corrdict[p][c].to_asdf(file=os.path.join(outdir,fnamebase),v=v)
            elif output_structure.lower() == "source" or output_structure.lower() == "s":
                localdir=os.path.join(outdir,corrdict[p][c].net[0]+'.'+corrdict[p][c].sta[0])
                corrdict[p][c].to_asdf(file=os.path.join(localdir,fnamebase),v=v)
            elif output_structure.lower() == "station-pair" or output_structure.lower() == "sp":
                localdir=os.path.join(outdir,p)
                corrdict[p][c].to_asdf(file=os.path.join(localdir,fnamebase),v=v)
            elif output_structure.lower() == "station-component-pair" or output_structure.lower() == "scp":
                localdir=os.path.join(outdir,p,c)
                corrdict[p][c].to_asdf(file=os.path.join(localdir,fnamebase),v=v)
            else:
                raise ValueError(output_structure + " is not recoganized. must be one of "+\
                        str(output_o)+" or "+str(output_o_short))

########################################################
################ XCORR ANALYSIS FUNCTIONS ##################
########################################################
def save_xcorr_amplitudes(dict_in,filenamebase=None):
    """
    This function saves the amplitude data for both negative and positive lags,
    for each xcorr component pair, to csv files.

    PARAMETERS:
    ----------------------------
    dict_in: dictionary containing peak amplitude information from one virtual source to all other receivers.
            This can be the output of get_xcorr_peakamplitudes().
    filenamebase: file name base of the csv file, default is source_component_peakamp.txt in the current dir.
    """
    source=dict_in['source']['name']
    lonS0,latS0,eleS0=dict_in['source']['location']

    #
    if filenamebase is None:
        filenamebase = source

    cc_comp=list(dict_in['cc_comp'].keys())

    for ic in range(len(cc_comp)):
        comp = cc_comp[ic]
        receivers=list(dict_in['cc_comp'][comp].keys())
        lonS=lonS0*np.ones((len(receivers),))
        latS=latS0*np.ones((len(receivers),))
        eleS=eleS0*np.ones((len(receivers),))
        comp_out=len(receivers)*[comp]
        source_out=len(receivers)*[source]

        lonR=[]
        latR=[]
        eleR=[]
        dist=[]
        peakamp_neg=[]
        peakamp_pos=[]
        peaktt_neg=[]
        peaktt_pos=[]
        az=[]
        baz=[]

        for ir in range(len(receivers)):
            receiver=receivers[ir]
            dist0=dict_in['cc_comp'][comp][receiver]['dist']
            dist.append(dist0)
            lonR.append(dict_in['cc_comp'][comp][receiver]['location'][0])
            latR.append(dict_in['cc_comp'][comp][receiver]['location'][1])
            eleR.append(0.0)
            az.append(dict_in['cc_comp'][comp][receiver]['az'])
            baz.append(dict_in['cc_comp'][comp][receiver]['baz'])
            peakamp_neg.append(np.array(dict_in['cc_comp'][comp][receiver]['peak_amplitude'])[0])
            peakamp_pos.append(np.array(dict_in['cc_comp'][comp][receiver]['peak_amplitude'])[1])
            peaktt_neg.append(np.array(dict_in['cc_comp'][comp][receiver]['peak_amplitude_time'])[0])
            peaktt_pos.append(np.array(dict_in['cc_comp'][comp][receiver]['peak_amplitude_time'])[1])


        outDF=pd.DataFrame({'source':source_out,'lonS':lonS,'latS':latS,'eleS':eleS,
                           'receiver':receivers,'lonR':lonR,'latR':latR,'eleR':eleR,
                           'az':az,'baz':baz,'dist':dist,'peakamp_neg':peakamp_neg,
                            'peakamp_pos':peakamp_pos,'peaktt_neg':peaktt_neg,
                            'peaktt_pos':peaktt_pos,'comp':comp_out})
        fname=filenamebase+'_'+comp+'_peakamp.txt'
        outDF.to_csv(fname,index=False)
        print('data was saved to: '+fname)
#
def shaping_corrdata(ccfile,wavelet,width,shift,trim_end=False,outdir=".",comp="ZZ",stack=True,
                        stack_method='robust',output_format="asdf",pair=None,verbose=True):
    """
    This is a wrapper to apply shaping wavelet to corrdata.data and save to files.

    =====PARAMETERS======
    ccfile: file containing correlation data.
    wavelet,width,shift: shaping wavelet parameters. See seisgo.types.CorrData.shaping() for details.
    outdir: output directory. Default is current folder:"."
    pair: station pair to process. May specify as a list or string. Default is None, processing all components. 
    comp: correlation component. May specify as a list or string. Default: "ZZ". Process all components if None.
    stack=True,stack_method='robust': save stack after shaping? Default is True.
    output_format: format to save the shapped data. Default "asdf".
    verbose: Default: True

    =====RETURNS====
    No return.
    """
    if output_format.lower() == "sac":
        fext="sac"
    elif output_format.lower() == "asdf":
        fext="h5"
    else:
        raise ValueError(output_format+" is not recoganized. use sac or asdf.")

    cdataall=extract_corrdata(ccfile)
    pairall=list(cdataall.keys())
    if isinstance(pair,str):pair=[pair]
    if pair is None: pair = pairall 
    #loop through all pairs
    for pair0 in pair:
        if isinstance(comp,str):comp=[comp]
        compall=list(cdataall[pair0].keys())
        if comp is None: comp=compall
        for comp0 in compall:
            cdata=cdataall[pair0][comp0]

            # CONVOLVE
            cdata.shaping(width,shift,wavelet=wavelet,trim_end=trim_end,overwrite=True)
            #
            fbase=pair0+'_'+comp0+'_'+cdata.side
            #save individual NCFs
            if output_format.lower() == "sac":
                outdir0=os.path.join(outdir,pair0)
                cdata.save(output_format,outdir=outdir0,v=verbose)
            elif output_format.lower() == "asdf":
                outdir0=outdir
                cdata.save(output_format,file=fbase+"."+fext,outdir=outdir0,v=verbose)

            #stack and overwrite
            if stack:
                cdata.stack(method=stack_method,overwrite=True)
                if output_format.lower() == "sac":
                    corrtime=obspy.UTCDateTime(cdata.time)
                    ofile=str(corrtime).replace(':', '-')+'_'+cdata.id+'_'+cdata.cc_comp+'_'+cdata.side+'_stack.'+fext
                elif output_format.lower() == "asdf":
                    ofile =  fbase+"_stack."+fext
                cdata.save(output_format,outdir=outdir0,file=ofile,v=verbose)

#
def get_stationpairs(ccfiles,getcclist=False,verbose=False,gettimerange=False):
    """
    Extract unique station pairs from all cc files in ASDF format.

    ====PARAMETERS===
    ccfiles: a list of cc files.
    getcclist: get cc component list. default False.
    verbose: verbose flag; default False.
    ====RETURNS===
    pairs_all: all netstaion pairs in the format of NET1.STA1_NET2.STA2
    netsta_all: all net.sta (unique list)
    ccomp_all: all unique list of cc components.
    """
    if isinstance(ccfiles,str):ccfiles=[ccfiles]
    pairs_all = []
    ccomp_all=[]
    if gettimerange:
        ts=[]
        te=[]
    for f in ccfiles:
        # load the data from daily compilation
        try:
            ds=pyasdf.ASDFDataSet(f,mpi=False,mode='r')

            pairlist   = ds.auxiliary_data.list()
            if getcclist:
                for p in pairlist:
                    chanlist=ds.auxiliary_data[p].list()
                    for c in chanlist:
                        if gettimerange:
                            para=ds.auxiliary_data[p][c].parameters
                            ttime=para['time']
                            if 'time_mean' in list(para.keys()):
                                ttime += para['time_mean']
                            ts.append(np.min(ttime))
                            te.append(np.max(ttime))
                        c1,c2=c.split('_')
                        ccomp_all.extend(c1[-1]+c2[-1])
                ccomp_all=sorted(set(ccomp_all))
            elif gettimerange:
                for p in pairlist:
                    chanlist=ds.auxiliary_data[p].list()
                    for c in chanlist:
                        para=ds.auxiliary_data[p][c].parameters
                        ttime=para['time']
                        if 'time_mean' in list(para.keys()):
                            ttime += para['time_mean']
                        ts.append(np.min(ttime))
                        te.append(np.max(ttime))

            pairs_all.extend(pairlist)
            pairs_all=sorted(set(pairs_all))

        except Exception as e:
            if verbose:print('continue! no data in %s: %s'%(f,str(e)))
            continue

    netsta_all=[]
    for p in pairs_all:
        netsta=p.split('_')
        netsta_all.extend(netsta)

    netsta_all=sorted(set(netsta_all))

    if getcclist:
        if gettimerange:
            trange=[np.min(ts),np.max(te)]
            return pairs_all,netsta_all,ccomp_all,trange
        else:
            return pairs_all,netsta_all,ccomp_all
    else:
        if gettimerange:
            trange=[np.min(ts),np.max(te)]
            return pairs_all,netsta_all,trange
        else:
            return pairs_all,netsta_all

def get_cctimerange(ccfiles,verbose=False):
    """
    Extract time range from all cc files in ASDF format.

    ====PARAMETERS===
    ccfiles: a list of cc files.
    verbose: verbose flag; default False.
    ====RETURNS===
    ts,te: start and end time of all ccdata.
    """
    if isinstance(ccfiles,str):ccfiles=[ccfiles]
    ts_all = []
    te_all = []
    for f in ccfiles:
        # load the data from daily compilation
        corrdata=extract_corrdata(f,dataless=True)
        plist=list(corrdata.keys())
        for p in plist:
            clist=list(corrdata[p].keys())
            c=clist[0]
            if corrdata[p][c].substack:
                ts_all.append(corrdata[p][c].time[0])
                te_all.append(corrdata[p][c].time[-1])
            else:
                ts_all.append(corrdata[p][c].time)
                te_all.append(corrdata[p][c].time)
        del corrdata

    ts=np.array(ts_all).min()
    te=np.array(te_all).max()

    return ts,te

def extract_corrdata(sfile,pair=None,comp=['all'],mpi=False,dataless=False):
    '''
    extract the 2D matrix of the cross-correlation functions and the metadata for a certain time-chunck.
    PARAMETERS:
    --------------------------
    sfile: cross-correlation functions outputed by SeisGo cross-correlation workflow
    pair: net1.sta1-net2.sta2 pair to extract, default is to extract all pairs.
    comp: cross-correlation component or a list of components to extract, default is all components.

    RETURN:
    --------------------------
    corrdict: a dictionary that contains all extracted correlations, which each key as the station pair name.
                for each station pair, the correlaitons are saved as a list of CorrData objects.
    USAGE:
    --------------------------
    extract_corrdata('temp.h5',comp='ZZ')
    '''
    #check help or not at the very beginning

    # open data for read
    if isinstance(pair,str): pair=[pair]
    if isinstance(comp,str): comp=[comp]
    corrdict=dict()

    try:
        ds = pyasdf.ASDFDataSet(sfile,mode='r',mpi=mpi)
        # extract common variables
        spairs_all = ds.auxiliary_data.list()
    except Exception:
        print("return empty! cannot open %s to read"%sfile)
        return corrdict
    if pair is None: pair=spairs_all

    overlap_pair=list(set(pair) & set(spairs_all))
    if len(overlap_pair)<1:
        print(str(pair)+" not found. Return empty.")
        return corrdict

    for spair in overlap_pair:
        ttr = spair.split('_')
        snet,ssta = ttr[0].split('.')
        rnet,rsta = ttr[1].split('.')
        path_lists = ds.auxiliary_data[spair].list()
        corrdict[spair]=dict()
        for ipath in path_lists:
            schan,rchan = ipath.split('_')
            cc_comp=schan[-1]+rchan[-1]
            if cc_comp in comp or comp == ['all'] or comp ==['ALL']:
                try:
                    para=ds.auxiliary_data[spair][ipath].parameters
                    substack,ttime,dt,maxlag,az,baz,cc_method,dist,slat,slon,rlat,rlon = \
                                [para['substack'],para['time'],\
                                para['dt'],para['maxlag'],para['azi'],para['baz'],\
                                para['cc_method'],para['dist'],para['latS'],para['lonS'],\
                                para['latR'],para['lonR']]
                    if "eleS" in  list(para.keys()):
                        sele = para['eleS']
                    else:
                        sele = 0.0
                    if "eleR" in  list(para.keys()):
                        rele = para['eleR']
                    else:
                        rele = 0.0
                    if "cc_len" in  list(para.keys()):
                        cc_len = para['cc_len']
                    else:
                        cc_len = None
                    if "cc_step" in  list(para.keys()):
                        cc_step = para['cc_step']
                    else:
                        cc_step = None
                    if "side" in  list(para.keys()):
                        side = para['side']
                    else:
                        side = "A"
                    ##special handling of time, in case time_mean is saved to reduce the attribute memory_size
                    if "time_mean" in list(para.keys()):
                        tmean=para["time_mean"]
                        ttime = np.float64(ttime) + tmean
                    if "stack_method" in list(para.keys()):
                        stack_method=para["stack_method"]
                    else:
                        stack_method=None
                    if not dataless: data = np.array(ds.auxiliary_data[spair][ipath].data)
                    else: data = None
                except Exception:
                    print('continue! something wrong with %s %s'%(spair,ipath))
                    continue

                corrdict[spair][cc_comp]=CorrData(net=[snet,rnet],sta=[ssta,rsta],loc=['',''],\
                                                chan=[schan,rchan],lon=[slon,rlon],lat=[slat,rlat],
                                                ele=[sele,rele],cc_comp=cc_comp,dt=dt,lag=maxlag,
                                                cc_len=cc_len,cc_step=cc_step,dist=dist,az=az,
                                                baz=baz,time=ttime,data=data,stack_method=stack_method,
                                                substack=substack,side=side,misc=para)
                if "type" in  list(para.keys()): corrdict[spair][cc_comp].type=para['type']

    return corrdict

def save_corrfile_to_sac(cfile,rootdir='.',pair=None,comp=['all'],v=True):
    """
    Save correlation files in ASDF to sac files.

    === PARAMETERS ===
    cfile: correlation file from SeisGo workflow. It could be a list of files.
    rootdir: folder to save the converted sac files. this is the root folder, not
            the folder for individual sources/receivers, which will be created
            by this function. Default is the current directory.
    pair: net1.sta1_net2.sta2 pair to extract, default is to extract all pairs.
    comp: cross-correlation component or a list of components to extract, default is 'all'.
    v: verbose or not, default is True.
    """
    if isinstance(cfile,str):cfile=[cfile]
    if isinstance(pair,str): pair=[pair]

    nfile=len(cfile)

    for cf in cfile:
        if v: print('working on file: '+cf.split('/')[-1])

        corrdict=extract_corrdata(cf)
        pairs_all=list(corrdict.keys())
        if pair is None:
            extract_pair=pairs_all
        else:
            extract_pair=pair

        for p in extract_pair:
            if p in pairs_all:
                netsta1,netsta2=p.split('_')
                outdir=os.path.join(rootdir,netsta1,netsta2)

                comp_all=list(corrdict[p].keys())
                for c in comp_all:
                    if c in comp or comp == ['all'] or comp ==['ALL']:
                        corrdict[p][c].to_sac(outdir=outdir)
            else:
                print('Pair %s not found. Skip.'%(p))
                continue
