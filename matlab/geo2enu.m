function [xEast, yNorth, zUp] = geo2enu(lat, lon, alt, home)
%GEO2ENU  Geodetic to local east/north/up, without any toolbox.
%
%   [XEAST, YNORTH, ZUP] = GEO2ENU(LAT, LON, ALT, HOME) converts geodetic
%   coordinates to a local Cartesian frame centred on HOME, a 3-element
%   vector [refLat, refLon, refAlt] in degrees and metres.
%
%   Drop-in replacement for latlon2local (Automated Driving Toolbox): same
%   argument order, same return order. Uses the same flat-earth
%   approximation, with the WGS84 meridional and normal radii of curvature
%   evaluated at the reference latitude.
%
%   Agreement with a rigorous ECEF-based ENU transform is better than 5 cm
%   over a 1 km box, checked at latitudes from -37 to +54 degrees. That is
%   far below GNSS noise for survey-sized areas. It is a local
%   approximation and is not intended for spans of tens of kilometres.
%
%   See also ENU2GEO, READPULSECSV.

    [rMeridional, rNormal] = localEarthRadii(home(1));
    xEast  = (lon - home(2)) .* (pi/180) .* rNormal .* cosd(home(1));
    yNorth = (lat - home(1)) .* (pi/180) .* rMeridional;
    zUp    = alt - home(3);
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
