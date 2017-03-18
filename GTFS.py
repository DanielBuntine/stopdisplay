
# coding: utf-8

# In[ ]:

stopid='1076'
RTcolnames=['RTUpdate','RTVehicle','RTDelay','RTTime','RTTimeDisplay','RTTimeCountdown']
RTupdateinterval=30
font_std=("Helvetica", 16)
font_bold=("Helvetica", 16,'bold')
font_time=("Helvetica", 24,'bold')
viewrows=10 #rows
viewcols=5 #columns
latestdate=dt.date.today()

print('Starting...')

from google.transit import gtfs_realtime_pb2
import urllib.request
import pandas as pd
import datetime as dt
import gtfstk as gt
import time
import numpy as np
import multiprocessing as mp
from contextlib import suppress
import tkinter as tk

rtget = dt.datetime.min
rtfeed = gtfs_realtime_pb2.FeedMessage()

def dl_gtfs():
    url = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"

    file_name = url.split('/')[-1]
    u = urllib.request.urlopen(url)
    f = open(file_name, 'wb')
    meta = u.info()
    file_size = int(u.getheader("Content-Length"))
    print("Downloading: %s Bytes: %s" % (file_name, file_size))

    file_size_dl = 0
    block_sz = 8192
    laststatus=-1
    while True:
        buffer = u.read(block_sz)
        if not buffer:
            break

        file_size_dl += len(buffer)
        f.write(buffer)
        status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
        status = status + chr(8)*(len(status)+1)
        
        if (file_size_dl * 100. / file_size) - laststatus > 1:
            print(status)
            laststatus = file_size_dl * 100. / file_size

    f.close()


def conv_time(timestr):
    hours, minutes, seconds = map(int, timestr.split(':'))
    return dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)

def get_stoptt(stopid,ttdate):
    print('Loading stop timetable for '+str(stopid)+' on '+str(ttdate))
    stoptt=gt.calculator.get_stop_timetable(feed,stopid,ttdate.strftime('%Y%m%d'))
    stoptt['arrival_time']=stoptt['arrival_time'].apply(lambda x: dt.datetime.combine(ttdate, dt.time())+conv_time(x))
    stoptt['departure_time']=stoptt['departure_time'].apply(lambda x: dt.datetime.combine(ttdate, dt.time())+conv_time(x))
    stoptt=stoptt.merge(feed.routes[['route_id','route_short_name','route_color','route_text_color']],on='route_id',how='left',copy='False')
    stoptt=pd.concat([pd.DataFrame([],index=stoptt.index, columns=RTcolnames), stoptt], axis=1)
    print('Stop timetable ready')
    return stoptt

def get_stoptt_RT(stopid,ttdate):
    stoptt=get_stoptt(stopid,ttdate)
    if len(stoptt)>0:
        stoptt['RTTimeDisplay']=stoptt['departure_time']
        stoptt=apply_rtfeed(stoptt)
    return stoptt

def get_rtfeed():
    global rtget
    with suppress(Exception):
        response = urllib.request.urlopen('https://gtfsrt.api.translink.com.au/Feed/SEQ',timeout=(RTupdateinterval-5))
        rtfeed.ParseFromString(response.read())
        rtget=dt.datetime.now()

def refresh_countdown(stoptt):
    stoptt['RTTimeCountdown']=(stoptt['RTTimeDisplay'])-dt.datetime.now()
    return stoptt

def apply_rtfeed(stoptt):
    if len(stoptt)==0:
        print('No services')
        return stoptt
    else:
        global rtget

        if ((dt.datetime.now()-rtget)>dt.timedelta(seconds=RTupdateinterval))==True:
            print('Updating realtime feed')
            get_rtfeed()
        else:
            print('Real-time new enough')


        for entity in rtfeed.entity:
            lineitem=stoptt.trip_id.isin([entity.trip_update.trip.trip_id])
            if len(stoptt[lineitem])>0:
                #print(entity.trip_update.trip.trip_id)      
                #print(entity.trip_update.trip)
                if entity.trip_update.trip.schedule_relationship==3: #3 - Trip cancelled
                    stoptt.loc[lineitem, "RTUpdate"] = 'Cancelled'
                else:
                    stoptt.loc[lineitem, "RTVehicle"] = entity.trip_update.vehicle.id
                    for stop_update in entity.trip_update.stop_time_update:
                        if stop_update.stop_id==stopid:
                            if stop_update.schedule_relationship==1: #1 - Stop skipped
                                stoptt.loc[lineitem, "RTUpdate"] = 'Stop skipped'      
                            else:
                                stoptt.loc[lineitem, "RTDelay"] = stop_update.departure.delay
                                stoptt.loc[lineitem, "RTTime"] = dt.datetime.fromtimestamp(stop_update.departure.time)
            elif entity.trip_update.trip.schedule_relationship==1: #1 - Trip added
                for stop_update in entity.trip_update.stop_time_update:
                    if stop_update.stop_id==stopid:
                        print('Adding stop')
                        newroutesdf=feed.routes[feed.routes.route_id.isin([entity.trip_update.trip.route_id])]
                        if len(newroutesdf)>0:
                            routecolor=newroutesdf['route_color'].iloc[0]
                            routetextcolor=newroutesdf['route_text_color'].iloc[0]
                            routeshort=newroutesdf['route_short_name'].iloc[0]
                        else:
                            routecolor='000000'
                            routetextcolor='FFFFFF'
                            routeshort='Extra service'
                        stoptt=stoptt.append(pd.DataFrame([[entity.trip_update.trip.trip_id,
                                                     entity.trip_update.trip.route_id,
                                                     stop_update.departure.delay,
                                                     dt.datetime.fromtimestamp(stop_update.departure.time),
                                                     stop_update.stop_id,
                                                     routecolor,
                                                     routetextcolor,
                                                     routeshort,
                                                     routeshort,
                                                     'Added'
                                                    ]],columns=['trip_id',
                                                                'route_id',
                                                                'RTDelay',
                                                                'RTTime',
                                                                'stop_id',
                                                                'route_color',
                                                                'route_text_color',
                                                                'route_short_name',
                                                                'trip_headsign',
                                                                'RTUpdate']))

        stoptt['RTTimeDisplay']=stoptt['RTTime']
        stoptt['RTTimeDisplay']=stoptt.apply(lambda row: row["departure_time"] if pd.isnull(row["RTTime"]) == True else row["RTTime"], axis=1) 

        stoptt=refresh_countdown(stoptt)

        stoptt=stoptt.sort_values(by='RTTimeDisplay').reset_index(drop=True)
    return stoptt

def get_stop_subset(stoptt):
    subset=stoptt[(stoptt['RTTimeDisplay'] > dt.datetime.now()-dt.timedelta(minutes=5))]
    return subset


def sec_to_min(seconds,round10=False,roundmin=False):
    if roundmin==False:
        if round10==True:
            seconds=int(round(seconds, -1))
        mins=int(seconds/60)
        secs=abs(int(seconds-mins*60))
        mins=abs(mins)
        return str(mins)+':'+"{:0>2d}".format(secs)
    else:
        return str(abs(round(seconds/60)))

def delay_disp(seconds):
    if pd.isnull(seconds)==True:
        return 'No RT data'
    elif seconds>30:
        return sec_to_min(seconds,False,True)+' min late'
    elif seconds>-30:
        return 'On time'
    elif seconds<=-30:
        return sec_to_min(seconds,False,True)+' min early'
    else:
        return 'Unknown'
    
def due_disp(seconds,RT):
    if RT==True:
        if seconds<-30:
            return '-'+sec_to_min(seconds,True)
        elif seconds<0:
            return 'Now'
        elif seconds<30:
            return 'Now'
        elif seconds<600:
            return sec_to_min(seconds,True)
        elif pd.isnull(seconds)==False:
            return str(int(seconds/60)) + ' mins'
        else:
            return '???'
    else:
        if seconds<0:
            return 'Sched -'+sec_to_min(seconds,True)
        elif seconds<600:
            return sec_to_min(seconds,True)
        elif pd.isnull(seconds)==False:
            return str(int(seconds/60)) + ' mins'
        else:
            return '???'
        

def refresh_disp():
    global subset
    global rtget
    
    
    if ((dt.datetime.now()-rtget)>dt.timedelta(seconds=RTupdateinterval)):
        subset=apply_rtfeed(get_stop_subset(subset))
    else:
        subset=refresh_countdown(subset)
        
    set_text_disp()
    root.after(1000, refresh_disp)

def set_text_disp(initial=False):
    global subset
    global clock
    global displabels
    global latestdate
   
    clock.set(time.strftime('%X'))
    
    for c in range(min(len(subset),viewrows)):
        for i in range(viewcols):
            if subset['RTUpdate'].iloc[c]=='Added':
                disptext[c][0].set('Extra')
            else:
                disptext[c][0].set(subset['departure_time'].iloc[c].strftime('%H:%M'))
            disptext[c][1].set(subset['route_short_name'].iloc[c])
            disptext[c][2].set(subset['trip_headsign'].iloc[c])
            disptext[c][3].set(delay_disp(subset['RTDelay'].iloc[c]))
            disptext[c][4].set(due_disp(subset['RTTimeCountdown'].iloc[c].total_seconds(),(True if pd.isnull(subset['RTTime'].iloc[c])==False else False)))

            displabels[c][0].configure(fg='white')
            displabels[c][2].configure(fg='white')
            displabels[c][3].configure(fg='white')
            displabels[c][4].configure(fg='white')
            
            if -30 <= subset['RTDelay'].iloc[c] <= 30:
                displabels[c][3].configure(fg='#00CC00')
            elif subset['RTDelay'].iloc[c] < -30:
                displabels[c][3].configure(fg='#3399FF')
            elif subset['RTDelay'].iloc[c] > 30:
                displabels[c][3].configure(fg='#FF0000')
            else:
                displabels[c][3].configure(fg='#404040')
                
            if pd.isnull(subset['RTTime'].iloc[c])==False:
                if subset['RTTimeCountdown'].iloc[c]<dt.timedelta(seconds=-30):
                    displabels[c][0].configure(fg='#404040')
                    displabels[c][2].configure(fg='#404040')
                    displabels[c][3].configure(fg='#404040')
                    displabels[c][4].configure(fg='#404040')
        
            
            if initial==False:
                displabels[c][1].configure(bg='#'+subset['route_color'].iloc[c], fg='#'+subset['route_text_color'].iloc[c])

    if initial==False:
        if len(subset)<viewrows:
            latestdate += dt.timedelta(days=1)
            subset=subset.append(get_stop_subset(get_stoptt_RT(stopid,latestdate)))

print('Loaded functions')


# In[3]:

print('Loading GTFS')
dl_gtfs()
feed = gt.read_gtfs(r'SEQ_GTFS.zip', dist_units='km')
print('GTFS Ready')


# In[96]:

subset=get_stop_subset(get_stoptt_RT(stopid,latestdate))

while (len(subset)<viewrows):
    latestdate += dt.timedelta(days=1)
    subset=subset.append(get_stop_subset(get_stoptt_RT(stopid,latestdate)))
           
root = tk.Tk()
root.resizable(width=False, height=False)
#root.attributes("-fullscreen", True)
root.geometry('{}x{}'.format(800, 480))

displabels = []
disptext = []
clock=tk.StringVar()

stopname=feed.stops.where(feed.stops['stop_id']==stopid)['stop_name'].dropna().iloc[0]

stopframe = tk.Frame(root,bg="black")
stopframe.pack(fill='both', expand=1)
clockframe=tk.Label(stopframe,font=font_time,fg="yellow",bg="black",textvariable=clock)
clockframe.grid(row=1,column=1,sticky='nesw')
stopnameframe=tk.Label(stopframe,font=font_time,fg="yellow",bg="black",text=stopname)
stopnameframe.grid(row=1,column=2,sticky='nesw')
timeframe = tk.Frame(stopframe,bg="black")
timeframe.grid(row=2,column=1,sticky='nesw',columnspan=2)

stopframe.grid_rowconfigure(1, weight=1)
stopframe.grid_rowconfigure(2, weight=5)
stopframe.grid_columnconfigure(1, weight=1)
stopframe.grid_columnconfigure(2, weight=1)


for c in range(min(len(subset),viewrows)):
    disptext.append([])
    displabels.append([])
    for i in range(viewcols):
        disptext[c].append(tk.StringVar())
        if i==1:
            displabels[c].append(tk.Label(timeframe,font=font_bold, textvariable=disptext[c][i],bg='#'+subset['route_color'].iloc[c], fg='#'+subset['route_text_color'].iloc[c], relief='raised'))
            displabels[c][i].grid(row=c,column=i,sticky='nesw')
        elif i==4:
            displabels[c].append(tk.Label(timeframe,font=font_bold, textvariable=disptext[c][i],bg='black'))
            displabels[c][i].grid(row=c,column=i)
        else:
            displabels[c].append(tk.Label(timeframe,font=font_std, textvariable=disptext[c][i],bg='black'))
            displabels[c][i].grid(row=c,column=i)

set_text_disp(True)

for c in range(min(len(subset),viewrows)):
    timeframe.grid_rowconfigure(c, weight=1)

for i in range(viewcols):
    timeframe.grid_columnconfigure(i, weight=1)

root.after(1000, refresh_disp)
root.mainloop()


# In[94]:

subset

