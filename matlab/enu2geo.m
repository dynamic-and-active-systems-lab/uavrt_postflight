function [lat, lon, alt] = enu2geo(xEast, yNorth, zUp, home)
%ENU2GEO  Local east/north/up to geodetic, without any toolbox.
%
%   [LAT, LON, ALT] = ENU2GEO(XEAST, YNORTH, ZUP, HOME) converts a local
%   Cartesian frame centred on HOME back to geodetic coordinates. HOME is
%   [refLat, refLon, refAlt] in degrees and metres.
%
%   Drop-in replacement for local2latlon (Automated Driving Toolbox): same
%   argument order, same return order. Exact inverse of GEO2ENU.
%
%   Because the transform is linear in xEast and yNorth independently, a
%   rectangular ENU grid maps to an exactly rectangular latitude/longitude
%   box. That is what makes a KML GroundOverlay of a gridded field exact
%   rather than approximate.
%
%   See also GEO2ENU, KMZWRITE.

    [rMeridional, rNormal] = localEarthRadii(home(1));
    lon = home(2) + xEast  .* (180/pi) ./ (rNormal .* cosd(home(1)));
    lat = home(1) + yNorth .* (180/pi) ./ rMeridional;
    alt = zUp + home(3);
end


function [rMeridional, rNormal] = localEarthRadii(refLat)
    a  = 6378137.0;             % WGS84 semi-major axis, m
    f  = 1/298.257223563;       % WGS84 flattening
    e2 = f*(2 - f);
    s  = sind(refLat);
    d  = 1 - e2*s.^2;
    rNormal     = a./sqrt(d);
    rMeridional = a.*(1 - e2)./(d.^1.5);
end
