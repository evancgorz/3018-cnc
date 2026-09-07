# Pine Live remote setup

Pine Live is optional and remains disabled until the operator enables it from
the Preview & Run page. It exposes the Pine web companion only through the
computer's loopback interface and asks the official Tailscale client to Serve
that endpoint on HTTPS port 8443.

1. Install the official Tailscale client on the Pine computer and sign in to
   the desired tailnet.
2. Install Tailscale on the iPhone and sign in to the same tailnet.
3. In Pine, open **Preview & Run → Open Pine Live → Enable mobile**.
4. Wait for the status to show **Tailscale ready**, then scan the QR code or
   open the displayed HTTPS address from the iPhone.
5. Enter Pine's one-time pairing code. Pairing is still required even when
   both devices are members of the same tailnet.

Pine uses only its dedicated Serve mapping. It does not enable Funnel, change
the firewall, configure a router, or alter unrelated Tailscale Serve entries.
If port 8443 is occupied by another service, Pine refuses to replace it.

Keep a physical emergency stop available. Pine Live is for status, camera
awareness, Pause, Resume, and guarded Abort; it is not a safety interlock.
