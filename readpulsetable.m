function [T, warnMsg] = readpulsetable(fullFilePath)
%READPULSETABLE  Read a TagTracker / MavlinkTagController2 pulse log into a table.
%
%   T = READPULSETABLE(FILE) returns a table of pulse records with stable
%   column names, regardless of which build of TagTracker wrote the log.
%
%   [T, WARNMSG] = READPULSETABLE(FILE) also returns a char warning, empty
%   when nothing was unusual, describing records that were dropped or a
%   header layout that was not recognised.
%
%   Columns returned:
%     command_id  tag_id  frequency_hz  start_time_seconds
%     predict_next_start_seconds  snr  stft_score  group_seq_counter
%     group_ind  group_snr  noise_psd  detection_status  confirmed_status
%     lat  lon  alt_rel
%
%   Rows are sorted by start_time_seconds.
%
%   Why this exists rather than a plain readtable:
%
%   1. Four header variants have shipped. 2023 builds wrote no header at
%      all and 20 columns. Builds through 2026-04 wrote
%        "# 7, tag_id, ... position_x, _y, _z, orientation_x, _y, _z, _w, ..."
%      TagTracker master since 2026-04-10 writes
%        "# 1, tag_id, ... latitude, longitude, altitude_rel, roll_deg, ..."
%      In all of them the first 16 fields of a pulse record are in the same
%      order and columns 14/15/16 are latitude/longitude/altitude, so this
%      reads positionally and does not care what the header calls them.
%
%   2. readtable needs the leading '#' stripped from the header by hand.
%      This does not.
%
%   3. The full pulse log interleaves 4-field rotation start/stop records.
%      readtable turns those into "pulses" carrying a latitude in the
%      tag_id column and NaN positions, which corrupts the tag list and any
%      local frame anchored on the first row. Those rows are dropped here,
%      along with records missing a time or a usable fix.
%
%   Named readpulsetable, not readpulsecsv, because uavrt_bearing and
%   uavrt_localization_utils already define readpulsecsv with a different
%   contract: [pulses, commands] returning PulseStruct/CommandStruct
%   vectors. Two functions of the same name shadow each other on the MATLAB
%   path, so whichever lost would fail silently. This one returns a table.
%
%   See also KMZWRITE, GEO2ENU.

    nKeep   = 16;
    warnMsg = '';

    raw = readlines(fullFilePath);
    raw = strip(raw);
    raw(raw == "" | ismissing(raw)) = [];
    if isempty(raw)
        error('readpulsetable:emptyFile', 'The file contains no data.');
    end

    % Header rows start with '#' or carry the column names.
    isHeader = startsWith(raw, "#") | contains(raw, "tag_id");
    hdr      = raw(isHeader);
    body     = raw(~isHeader);
    if isempty(body)
        error('readpulsetable:noPulses', 'The file contains no pulse records.');
    end

    % Warn if a future format moves the position fields off 14/15/16.
    if ~isempty(hdr)
        tok = strip(split(hdr(1), ","));
        if numel(tok) >= nKeep
            latName = lower(tok(14));
            if ~(contains(latName, "latitude") || contains(latName, "position_x"))
                warnMsg = sprintf(['Unrecognised pulse log header. Column 14 is "%s", ' ...
                    'expected "latitude" or "position_x". Positions may be wrong.'], tok(14));
            end
        end
    end

    n    = numel(body);
    M    = nan(n, nKeep);
    keep = false(n, 1);
    for i = 1:n
        v = sscanf(char(body(i)), '%f,').';
        if numel(v) >= nKeep
            M(i, :) = v(1:nKeep);
            keep(i) = true;
        end
    end
    M = M(keep, :);
    if isempty(M)
        error('readpulsetable:noPulses', ...
            'No complete pulse records found (rotation markers only?).');
    end

    % Keep only the dominant record type, then only rows with a usable time
    % and a plausible fix.
    M = M(M(:,1) == mode(M(:,1)), :);
    ok = isfinite(M(:,4)) & isfinite(M(:,2)) & ...
         isfinite(M(:,14)) & isfinite(M(:,15)) & ...
         abs(M(:,14)) <= 90 & abs(M(:,15)) <= 180 & ...
         ~(M(:,14) == 0 & M(:,15) == 0);
    nDropped = sum(~ok);
    M = M(ok, :);
    if isempty(M)
        error('readpulsetable:noPulses', ...
            'No pulse records with a valid time and position.');
    end
    if nDropped > 0
        warnMsg = strtrim(sprintf('%s\n%d record(s) dropped for a missing time or position.', ...
            warnMsg, nDropped));
    end

    M(:,16) = fillmissing(M(:,16), 'constant', 0);   % altitude is optional

    T = array2table(M, 'VariableNames', { ...
        'command_id', 'tag_id', 'frequency_hz', 'start_time_seconds', ...
        'predict_next_start_seconds', 'snr', 'stft_score', ...
        'group_seq_counter', 'group_ind', 'group_snr', 'noise_psd', ...
        'detection_status', 'confirmed_status', 'lat', 'lon', 'alt_rel'});

    % Pulses are logged as they arrive; sorting lets callers assume order.
    T = sortrows(T, 'start_time_seconds');
end
