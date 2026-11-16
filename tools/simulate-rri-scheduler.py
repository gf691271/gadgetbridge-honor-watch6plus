"""Static trace of the wear-aware stream scheduler, one tick at a time.

No device: this replays the decision table in
HuaweiSupportProvider.rriRepeat so the state machine can be checked before it runs a night.
Each row is 15 s.
"""
GRACE = 5 * 60
LIVENESS = 15 * 60
REOPEN = 90
WEAR_SILENCE = 8 * 60
PROBE_PERIOD = 15 * 60
PROBE_LENGTH = 3 * 60
PARKED_TIMEOUT = 45 * 60


class Sim:
    def __init__(self, name):
        self.name = name
        self.t = 0.0
        self.window_entered = None
        self.last_packet = -99999.0     # no packets ever
        self.last_beat = -99999.0
        self.last_probe = -99999.0
        self.probe_started = None
        self.stream_open = False
        self.probe_count = 0
        self.close_count = 0
        self.drop_count = 0
        self.worn = False
        self.log = []

    def tick(self):
        self.t += 15
        now = self.t
        if self.worn:
            # a worn watch answers with beats every ~14 s
            if self.stream_open:
                self.last_packet = now
                if int(now) % 60 < 15:
                    self.last_beat = now
        elif self.stream_open:
            # off wrist: the watch still answers, with empty packets
            self.last_packet = now

        if self.window_entered is None:
            self.window_entered = now
        heard = self.last_packet >= self.window_entered
        silence = now - self.last_packet
        off_wrist = now - self.last_beat > WEAR_SILENCE

        before = (self.stream_open, self.probe_started)
        if not heard and now - self.window_entered > GRACE:
            self.drop_count += 1
            self.window_entered = now
            self.log.append("drop: nothing since window start")
        elif off_wrist:
            if self.probe_started is not None and now - self.probe_started > PROBE_LENGTH:
                self.stream_open = False
                self.probe_started = None
                self.close_count += 1
                self.log.append("park")
            elif self.probe_started is None and now - self.last_probe > PROBE_PERIOD:
                self.last_probe = now
                self.probe_started = now
                self.stream_open = True
                self.probe_count += 1
                self.log.append("probe")
            elif silence > PARKED_TIMEOUT:
                self.drop_count += 1
                self.window_entered = now
                self.probe_started = None
                self.last_probe = -99999.0
                self.log.append("drop: parked and silent too long")
        else:
            if self.probe_started is not None:
                self.probe_started = None
                self.last_probe = -99999.0
                self.log.append("beat arrived, probe done")
            if silence > LIVENESS:
                self.drop_count += 1
                self.window_entered = now
                self.log.append("drop: liveness")
            elif not heard or silence > REOPEN:
                if not self.stream_open:
                    self.stream_open = True
                self.log.append("open")
        after = (self.stream_open, self.probe_started)
        if before != after and after[0]:
            self.log[-1] += " (stream open)"
        if before != after and not after[0]:
            self.log[-1] += " (stream closed)"

    def run(self, minutes, events=()):
        steps = minutes * 4
        for k in range(steps):
            for at, worn in events:
                if abs(self.t + 15 - at * 60) < 7.5:
                    self.worn = worn
            self.tick()

    def report(self):
        print("\n%s" % self.name)
        print("  probes %d, parks %d, link drops %d, minutes %d"
              % (self.probe_count, self.close_count, self.drop_count, self.t / 60))
        # how much of the time the stream was open
        # (recompute by rerunning is overkill; report the log length instead)
        print("  events: %s" % ", ".join(self.log[:8]) + (" ..." if len(self.log) > 8 else ""))


# 1. off the wrist for two hours (charging), then worn for six
s = Sim("charge 00:00-02:00, then worn 02:00-08:00")
s.worn = False
s.run(120)
s.worn = True
s.run(360)
s.report()

# 2. worn the whole time
s2 = Sim("worn the whole 8 h")
s2.worn = True
s2.run(480)
s2.report()

# 3. never worn
s3 = Sim("never worn")
s3.worn = False
s3.run(480)
s3.report()
