function kmzwrite(kmzPath, varargin)
%KMZWRITE  Write a KMZ containing a raster surface, contour lines, coloured
%          points and marker points. Requires no toolboxes.
%
%   KMZWRITE(FILE, 'Name', Value, ...) writes a Google Earth KMZ to FILE.
%   Every section is optional; supply only what you have.
%
%   Surface (all three required together):
%     'GridLat'          Matrix of latitudes, as produced by meshgrid
%     'GridLon'          Matrix of longitudes, same size
%     'GridValue'        Matrix of values, same size. NaN cells are written
%                        transparent, so a griddata result is fine as-is.
%     'SurfaceOpacity'   0..1, default 0.8
%     'ContourLevels'    Number of contour lines, default 10. Use 0 to omit
%                        them. They go in their own folder, switched off by
%                        default so the raster reads cleanly.
%
%   Coloured points:
%     'PointLat', 'PointLon'   Vectors of equal length
%     'PointAlt'               Vector of altitudes, default 0
%     'PointValue'             Vector driving the marker colour, default []
%     'PointAltitudeMode'      'absolute' | 'relativeToGround' |
%                              'clampToGround'. Default 'clampToGround'
%
%   Markers (e.g. a known tag position):
%     'MarkerLat', 'MarkerLon' Vectors of equal length
%     'MarkerName'             Char, or cellstr with one name per marker
%
%   Folder labels shown in the Google Earth tree:
%     'PointFolderName'        Default 'Points'
%     'MarkerFolderName'       Default 'Markers'
%
%   Labelling:
%     'Name'         Document name, default the output file name
%     'Description'  Document description
%     'ValueName'    What the values are, used in the legend and balloons.
%                    Default 'Value'
%
%   Example:
%     [X,Y]   = meshgrid(xVec, yVec);
%     [LAT,LON] = enuToGeodetic(X, Y, home);
%     kmzwrite('scan.kmz', 'GridLat',LAT, 'GridLon',LON, ...
%              'GridValue',snrGrid, 'ValueName','SNR (dB)', ...
%              'MarkerLat',tagLat, 'MarkerLon',tagLon, 'MarkerName','Tag');
%
%   Written to replace the kmltoolbox calls this project used to make. That
%   toolbox inlined a full <Style> block into every placemark and pointed
%   each marker icon at http://maps.google.com, so exports were roughly
%   three times larger than necessary and did not render without a network.
%   Here styles are declared once and referenced by styleUrl, and the marker
%   icon is packaged inside the kmz.

    %% ---- options ----------------------------------------------------
    [~, defaultName] = fileparts(kmzPath);
    opt = struct( ...
        'GridLat',           [], ...
        'GridLon',           [], ...
        'GridValue',         [], ...
        'SurfaceOpacity',    0.8, ...
        'ContourLevels',     10, ...
        'PointLat',          [], ...
        'PointLon',          [], ...
        'PointAlt',          [], ...
        'PointValue',        [], ...
        'PointAltitudeMode', 'clampToGround', ...
        'MarkerLat',         [], ...
        'MarkerLon',         [], ...
        'MarkerName',        'Marker', ...
        'PointFolderName',   'Points', ...
        'MarkerFolderName',  'Markers', ...
        'Name',              defaultName, ...
        'Description',       '', ...
        'ValueName',         'Value');

    if mod(numel(varargin), 2) ~= 0
        error('kmzwrite:badPairs', 'Options must be name/value pairs.');
    end
    known = fieldnames(opt);
    for i = 1:2:numel(varargin)
        name = varargin{i};
        if ~(ischar(name) || isstring(name))
            error('kmzwrite:badName', 'Option %d is not a name.', (i+1)/2);
        end
        hit = strcmpi(known, name);
        if ~any(hit)
            error('kmzwrite:unknownOption', 'Unknown option "%s".', char(name));
        end
        opt.(known{hit}) = varargin{i+1};
    end

    nBins    = 64;      % colour bins for points
    nLineCol = 16;      % colour bins for contour lines
    cmap     = turbo(nBins);

    haveGrid = ~isempty(opt.GridValue) && ~isempty(opt.GridLat) && ...
               ~isempty(opt.GridLon)   && any(isfinite(opt.GridValue(:)));
    if haveGrid && ~isequal(size(opt.GridLat), size(opt.GridLon), size(opt.GridValue))
        error('kmzwrite:gridSize', 'GridLat, GridLon and GridValue must be the same size.');
    end

    pLat = opt.PointLat(:);
    pLon = opt.PointLon(:);
    if numel(pLat) ~= numel(pLon)
        error('kmzwrite:pointSize', 'PointLat and PointLon must be the same length.');
    end
    nPts = numel(pLat);
    pAlt = localFill(opt.PointAlt(:), nPts, 0);
    pVal = opt.PointValue(:);
    if ~isempty(pVal) && numel(pVal) ~= nPts
        error('kmzwrite:pointSize', 'PointValue must match PointLat in length.');
    end

    mLat = opt.MarkerLat(:);
    mLon = opt.MarkerLon(:);
    if numel(mLat) ~= numel(mLon)
        error('kmzwrite:markerSize', 'MarkerLat and MarkerLon must be the same length.');
    end
    mName = opt.MarkerName;
    if ischar(mName) || isstring(mName)
        mName = repmat({char(mName)}, numel(mLat), 1);
    end

    %% ---- staging -----------------------------------------------------
    stage = [tempname, '_kmz'];
    mkdir(stage);
    mkdir(fullfile(stage, 'files'));
    cleanupStage = onCleanup(@() rmdir(stage, 's')); %#ok<NASGU>

    parts = {};
    parts{end+1} = sprintf('<?xml version="1.0" encoding="UTF-8"?>\n');
    parts{end+1} = sprintf('<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n');
    parts{end+1} = sprintf('<name>%s</name>\n', localEscape(opt.Name));
    if ~isempty(opt.Description)
        parts{end+1} = sprintf('<description>%s</description>\n', localEscape(opt.Description));
    end

    %% ---- shared styles ------------------------------------------------
    localWriteDotPng(fullfile(stage, 'files', 'dot.png'));
    for k = 1:nBins
        parts{end+1} = sprintf(['<Style id="p%02d"><IconStyle><color>%s</color>' ...
            '<scale>0.5</scale><Icon><href>files/dot.png</href></Icon></IconStyle>' ...
            '<LabelStyle><scale>0</scale></LabelStyle></Style>\n'], ...
            k-1, localKmlColor(cmap(k,:), 255)); %#ok<AGROW>
    end
    lineCmap = turbo(nLineCol);
    for k = 1:nLineCol
        parts{end+1} = sprintf(['<Style id="l%02d"><LineStyle><color>%s</color>' ...
            '<width>2</width></LineStyle></Style>\n'], ...
            k-1, localKmlColor(lineCmap(k,:), 255)); %#ok<AGROW>
    end
    parts{end+1} = sprintf(['<Style id="marker"><IconStyle><color>FF000000</color>' ...
        '<scale>1.4</scale><Icon><href>files/dot.png</href></Icon></IconStyle>' ...
        '</Style>\n']);

    %% ---- ground overlay ------------------------------------------------
    if haveGrid
        localWriteSurfacePng(fullfile(stage, 'files', 'surface.png'), opt.GridValue);

        LAT = opt.GridLat;
        LON = opt.GridLon;
        % GroundOverlay maps image edges to the box, but grid values sit at
        % cell centres, so the box grows by half a cell in each direction.
        halfLat = 0;
        halfLon = 0;
        if size(LAT, 1) > 1, halfLat = abs(LAT(2,1) - LAT(1,1))/2; end
        if size(LON, 2) > 1, halfLon = abs(LON(1,2) - LON(1,1))/2; end

        alphaHex = dec2hex(uint8(round(255*min(max(opt.SurfaceOpacity, 0), 1))), 2);
        parts{end+1} = sprintf(['<Folder><name>%s surface</name>\n' ...
            '<GroundOverlay><name>%s</name><color>%sffffff</color>\n' ...
            '<Icon><href>files/surface.png</href></Icon>\n' ...
            '<LatLonBox><north>%.10f</north><south>%.10f</south>' ...
            '<east>%.10f</east><west>%.10f</west></LatLonBox>\n' ...
            '</GroundOverlay></Folder>\n'], ...
            localEscape(opt.ValueName), localEscape(opt.ValueName), lower(alphaHex), ...
            max(LAT(:)) + halfLat, min(LAT(:)) - halfLat, ...
            max(LON(:)) + halfLon, min(LON(:)) - halfLon);
    end

    %% ---- contour lines, off by default ---------------------------------
    if haveGrid && opt.ContourLevels > 0
        lonVec = opt.GridLon(1,:);
        latVec = opt.GridLat(:,1).';
        C = contourc(lonVec, latVec, opt.GridValue, opt.ContourLevels);

        finiteG = opt.GridValue(isfinite(opt.GridValue));
        gLo = min(finiteG);
        gHi = max(finiteG);
        if gHi <= gLo, gHi = gLo + 1; end

        segs = {};
        k = 1;
        while k < size(C, 2)
            lev = C(1, k);
            np  = C(2, k);
            if np < 2 || k + np > size(C, 2)
                break
            end
            xs = C(1, k+1:k+np);
            ys = C(2, k+1:k+np);
            ci = min(max(round((lev - gLo)/(gHi - gLo)*(nLineCol - 1)) + 1, 1), nLineCol);
            segs{end+1} = sprintf(['<Placemark><name>%.4g</name>' ...
                '<styleUrl>#l%02d</styleUrl><LineString><tessellate>1</tessellate>' ...
                '<altitudeMode>clampToGround</altitudeMode>' ...
                '<coordinates>%s</coordinates></LineString></Placemark>\n'], ...
                lev, ci-1, sprintf('%.8f,%.8f,0 ', [xs; ys])); %#ok<AGROW>
            k = k + np + 1;
        end

        if ~isempty(segs)
            parts{end+1} = sprintf('<Folder><name>Contour lines</name><visibility>0</visibility>\n');
            parts{end+1} = strjoin(segs, '');
            parts{end+1} = sprintf('</Folder>\n');
        end
    end

    %% ---- coloured points -------------------------------------------------
    if nPts > 0
        if isempty(pVal)
            binIdx = repmat(nBins, 1, nPts);
            valTxt = repmat({''}, nPts, 1);
        else
            finiteP = pVal(isfinite(pVal));
            if isempty(finiteP) || numel(unique(finiteP)) == 1
                binIdx = repmat(nBins, 1, nPts);
            else
                vLo = min(finiteP);
                vHi = max(finiteP);
                binIdx = round((pVal(:).' - vLo)/(vHi - vLo)*(nBins - 1)) + 1;
                binIdx(~isfinite(binIdx)) = 1;
                binIdx = min(max(binIdx, 1), nBins);
            end
        end

        % The value name goes into the format string, so escape any percent.
        label = strrep(localEscape(opt.ValueName), '%', '%%');
        mode  = localEscape(opt.PointAltitudeMode);
        if isempty(pVal)
            fmt = ['<Placemark><styleUrl>#p%02d</styleUrl>' ...
                   '<Point><altitudeMode>' mode '</altitudeMode>' ...
                   '<coordinates>%.8f,%.8f,%.2f</coordinates></Point></Placemark>' char(10)];
            block = sprintf(fmt, [binIdx - 1; pLon(:).'; pLat(:).'; pAlt(:).']);
        else
            fmt = ['<Placemark><styleUrl>#p%02d</styleUrl>' ...
                   '<description>' label ' = %.4g</description>' ...
                   '<Point><altitudeMode>' mode '</altitudeMode>' ...
                   '<coordinates>%.8f,%.8f,%.2f</coordinates></Point></Placemark>' char(10)];
            block = sprintf(fmt, [binIdx - 1; pVal(:).'; pLon(:).'; pLat(:).'; pAlt(:).']);
        end
        parts{end+1} = sprintf('<Folder><name>%s</name>\n', localEscape(opt.PointFolderName));
        parts{end+1} = block;
        parts{end+1} = sprintf('</Folder>\n');
    end

    %% ---- markers ----------------------------------------------------------
    if ~isempty(mLat)
        parts{end+1} = sprintf('<Folder><name>%s</name>\n', localEscape(opt.MarkerFolderName));
        for i = 1:numel(mLat)
            parts{end+1} = sprintf(['<Placemark><name>%s</name><styleUrl>#marker</styleUrl>' ...
                '<Point><altitudeMode>clampToGround</altitudeMode>' ...
                '<coordinates>%.8f,%.8f,0</coordinates></Point></Placemark>\n'], ...
                localEscape(mName{i}), mLon(i), mLat(i)); %#ok<AGROW>
        end
        parts{end+1} = sprintf('</Folder>\n');
    end

    parts{end+1} = sprintf('</Document>\n</kml>\n');

    %% ---- write and zip -----------------------------------------------------
    kmlFile = fullfile(stage, 'doc.kml');
    fid = fopen(kmlFile, 'w');
    if fid < 0
        error('kmzwrite:open', 'Could not open %s for writing.', kmlFile);
    end
    fwrite(fid, unicode2native(strjoin(parts, ''), 'UTF-8'));
    fclose(fid);

    zipPath = [tempname, '.zip'];
    zip(zipPath, {'doc.kml', 'files'}, stage);
    if ~isfile(zipPath) && isfile([zipPath, '.zip'])
        zipPath = [zipPath, '.zip'];
    end
    movefile(zipPath, kmzPath, 'f');
end


function v = localFill(v, n, defaultValue)
    if isempty(v)
        v = repmat(defaultValue, n, 1);
    elseif isscalar(v)
        v = repmat(v, n, 1);
    elseif numel(v) ~= n
        error('kmzwrite:vectorSize', 'Expected %d elements, got %d.', n, numel(v));
    end
end


function out = localEscape(txt)
    out = char(txt);
    out = strrep(out, '&', '&amp;');
    out = strrep(out, '<', '&lt;');
    out = strrep(out, '>', '&gt;');
end


function hex = localKmlColor(rgbRow, alpha)
    % KML colours are aabbggrr, the reverse of the usual order.
    rgbRow = min(max(rgbRow(:).', 0), 1);
    v = uint8(round([alpha, 255*rgbRow(3), 255*rgbRow(2), 255*rgbRow(1)]));
    hex = sprintf('%02X%02X%02X%02X', v(1), v(2), v(3), v(4));
end


function localWriteDotPng(pngPath)
    % A white disc with a soft edge. White so the per-style <color> tint in
    % IconStyle reproduces the intended colour exactly.
    m = 64;
    [xx, yy] = meshgrid(linspace(-1, 1, m));
    r = hypot(xx, yy);
    alpha = min(max((0.90 - r)*(m/6), 0), 1);
    imwrite(ones(m, m, 3), pngPath, 'Alpha', alpha);
end


function localWriteSurfacePng(pngPath, G)
    % PNG row 1 is the north edge of a GroundOverlay, but row 1 of a meshgrid
    % is its south edge, hence the flip. NaN cells are written transparent.
    finiteMask = isfinite(G);
    lo = min(G(finiteMask));
    hi = max(G(finiteMask));
    if isempty(lo) || hi <= lo
        hi = lo + 1;
    end
    idx = round((G - lo)/(hi - lo)*255) + 1;
    idx(~finiteMask) = 1;
    idx = min(max(idx, 1), 256);

    cmap = turbo(256);
    rgb  = reshape(cmap(idx(:), :), [size(G), 3]);
    imwrite(flipud(rgb), pngPath, 'Alpha', flipud(double(finiteMask)));
end
