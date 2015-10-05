from astropy.coordinates import SkyCoord
import astropy.units as u


import datetime
from astropy.coordinates import SkyCoord
import astropy.units as u
import os
from subprocess import Popen
import threading

class Scheduler():
    schedule = []
    next_id = 1
    def __init__(self, drive=None):
        """
        A pythonic event scheduler for radio telescopes.
        The scheduler allows the driving and observations to be controlled for a radio telescope.

        Parameters
        ----------
        drive : Drive object
           The connection to the telescope drive, which will be used to control the pointing of the telescope.
        
        """
        # In the initialisation we should probably load at least the drive object!
        self.drive = drive
        
        # We should now run the scheduler in a subthread, so that it's still possible to edit the queue
        # while it's running
        self.sched_thread = threading.Thread(target=self._run, daemon=True)
        self.sched_thread.start()
        
    
    def _run(self):
        """
        Run the scheduler.
        The scheduler checks whether it's time to start either a slew event, or an observation
        event by looking at the observation shedule. If it is time to start one it spawns a 
        process to run the script, and allows it to run until the end of the scheduled observation
        time.
        
        """
        # Make sure that the schedule is correctly sorted, so the first entry will be the 
        # next scheduled observation
        self.sort()
        schedule = self.schedule
        
        current_job = None
        current_slew = None
        while True:
            # Need an infinite loop to continuously check the time
            if datetime.datetime.now > schedule[0]['slewstart'] and not current_slew and not current_job:
                # If nothing's happening already, but it's time something should be
                # then start the slew
                current_slew = True
                self.drive.goto(schedule[0]['position'])
                # The next few lines might, conceivably, not be the best way to do this
                while not self.drive.slewSuccess():
                    continue
                current_slew = None
                
            elif datetime.datetime.now > schedule[0]['start'] and not current_slew and not current_job:
                # The slew has completed (or there wasn't one), but there are no
                # on-going jobs, so we're free to start the script
                current_job = Popen(schedule[0]['script'])
                
            elif datetime.datetime.now > schedule[0]['end'] and current_job:
                # It's time to stop the observation, so let's send a SIGTERM
                current_job.terminate()
                current_job = None

                # if a 'then' directive has been added this should now be acted upon.
                if schedule[0]['then']:
                    procs = schedule[0]['then']
                    if procs is list:
                        for proc in procs:
                            if proc is str:
                                Popen(proc)
                            else:
                                proc[0](proc[1])
                        else:
                            if proc is str:
                                Popen(procs)
                            else:
                                proc[0](proc[1])
                
                # And let's remove the job from the scheduler
                del(a[0])
        
        
    def at(self, time, script=None, position=None, until=None, forsec=None, then=None):
        """
        Schedule the execution of a script and the pointing of the telescope to a specific location.
        
        Parameters
        ----------
        time : datetime or astropy Time object
           The time at which the observation should start, i.e. 
           the time when the script will be executed.
           
        script : str
           The filepath of the script which will conduct the 
           observation. This can currently be a Python script, any script with a Shebang
           or a GNU Radio flowchart.
           
        position : str or Astropy skycoord
           A parsable string containing the sky position at which 
           the observation should be conducted, or an astropy skycoord
           object, or the name of a source.
           
        until : datetime or astropy Time object
           The time at which the obervation should be ended. In the future 
           this can also be the string "set", in which case the 
           
        forsec : datetime delta or int
            The amount of time the observation should be run for, 
            or the datetime delta representing the time period of the 
            observation.

        then : {python callable, str}
            An instruction to carry out once the observation has been completed,
            for example, moving the telescope to the stow position.
        
        Returns
        -------
        int  
           The job number assigned to the observation.
           
        Notes
        -----
        The observation scheduler was written principly for the use 
        of the H1 telescope at the University of Glasgow's Acre Road 
        Observatory, however the aim of this project was to make a 
        sufficiently general utility that it could be transferred at least 
        to the Observatory's other radio telescopes. 
        
        The scheduler operates using a thread dedicated to maintaining and 
        checking the schedule. Every time a new item is added to the schedule 
        it is sorted, and the scheduler checks whether it is due to start an 
        observation. In order to ensure that an observation can start on time 
        the scheduler will move the telescope in advance, and so up to 2 minutes' 
        leeway is required between observations to allow this process to occur. 
        The scheduler attempts to predict this movement time in order to avoid 
        excessive outages during small movements.
        """
        
        # Should first check and then parse the various different isntructions,
        # but for now let's just settle with having something which can add a 
        # line to the schedule.
        
        self.sort
        schedule = self.schedule
        
        # Parse the position
        # To do, parse things other than skycoords
        if not type(position) is SkyCoord:
            # Need to parse stuff
            if not position:
                # For a None position, assume the zenith
                pass
        
        
        start = time
        
        if forsec:
            forsec = forsec
            end = time+datetime.timedelta(seconds=forsec)
        elif until:
            end = until
            
        # We can't schedule events in the past:
        if (end - datetime.datetime.now()).total_seconds() < 0:
            print "End time of job is in the past, the job has been rejected."
            return 0
        
        # We need to calculate the amount of time the telescope will require to
        # slew to the new location
        if self.drive:
            speed = float(self.drive.calibration.split()[0])
            speed = (speed / 3.141)*180
            slewtime  = drive.skycoord.separation(position).value / speed
        else: 
            slewtime = 0
        slewtime = datetime.timedelta(seconds=slewtime)
            
        slewstart = start - slewtime    
        # Check if this observation overlaps one already in the schedule,
        # see http://stackoverflow.com/a/9044111
        for item in self.schedule:
            latest_start = max(slewstart, item['start'])
            earliest_end = min(end, item['end'])
            overlap = (earliest_end - latest_start).total_seconds()
            if overlap > 0 and len(self.schedule)>0:
                if position.separation(item['position'])<1*u.deg:
                    # This observation is within the beam of the pre-exisiting 
                    # observation, so it can be carried-out simultaneously
                    # with the existing one
                    pass
                else:
                    print "The requested observation period overlaps with  \n\
                        a pre-existing scheduled observation [id={}], and this \n\
                        request has been rejected by the scheduler.".format(item['id'])
                    return 0
                
        # Now time to verify the script which has been requested
        if os.path.isfile(script) and os.access(script, os.X_OK):
            command = script
            if script[-2:len(script)] == 'py':
                # This is a python script, so we should preface it with "python"
                command = "python {}".format(script)
            elif script[-3:len(script)] == 'grc':
                # This is a GRC file which we'll need to compile to run
                command = "grcc -e {}".format(script)
            else: command = script

        # Then statements: Now time to verify the script which has been
        # requested for the then statements
        thencommands = []    
        if then:
                
            if then is not list: then = [then]
            for thenc in then:
                if os.path.isfile(thenc) and os.access(thenc, os.X_OK):
                    thencommands.append(thenc)
                    if thenc[-2:len(thenc)] == 'py':
                        # This is a python script, so we should preface it with "python"
                        thencommands.append( "python {}".format(thenc))
                    elif thenc[-3:len(thenc)] == 'grc':
                        # This is a GRC file which we'll need to compile to run
                        thencommands.append( "grcc -e {}".format(thenc) )
                    else: thencommands.append( thenc )
                elif hasattr(thenc, '__call__') :
                    # The command is probably a call to a function or other callable
                    thencommands.append( thenc )
    
        idn = self.next_id
        self.next_id += 1
        # There's no apparent overlap, so it's safe to add this job to the schedule.
        schedule.append({'id': idn, 'command':command, 'slewstart': slewstart, 'start':start, 'end':end, 'position':position, 'script': script, 'then': thencommands})
        self.sort()
    def sort(self):
        self.schedule = sorted(self.schedule, key=lambda k: k['start']) 