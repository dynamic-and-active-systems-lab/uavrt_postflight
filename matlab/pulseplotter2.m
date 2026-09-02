classdef pulseplotter2 < matlab.apps.AppBase
% pulseplotter2  Plain-file version of pulseplotter.
%
%   Same code as pulseplotter.mlapp, but an ordinary classdef file that
%   App Designer does not own and cannot overwrite. Run with: pulseplotter2

    % Requires these files alongside the app (same folder is enough):
    %   readpulsetable.m  reads any TagTracker pulse log header variant
    %   geo2enu.m       geodetic -> local ENU, replaces latlon2local
    %   enu2geo.m       local ENU -> geodetic, replaces local2latlon
    %   kmzwrite.m      writes the KMZ, replaces the kmltoolbox
    % They are shared with MONOPOLE_SCAN_MAPPING.m and need no toolboxes.

    % Properties that correspond to app components
    properties (Access = public)
        UIFigure                       matlab.ui.Figure
        GridLayout                     matlab.ui.container.GridLayout
        LeftPanel                      matlab.ui.container.Panel
        ControlGrid                    matlab.ui.container.GridLayout
        BearingEditField               matlab.ui.control.EditField
        BearingEditFieldLabel          matlab.ui.control.Label
        ConfidenceEditField            matlab.ui.control.EditField
        ConfidenceEditFieldLabel       matlab.ui.control.Label
        SpreadEditField                matlab.ui.control.EditField
        SpreadEditFieldLabel           matlab.ui.control.Label
        TakeoffElevEditField           matlab.ui.control.NumericEditField
        TakeoffElevEditFieldLabel      matlab.ui.control.Label
        PlotTagSwitch                  matlab.ui.control.Switch
        PlotTagSwitchLabel             matlab.ui.control.Label
        TagLonEditField                matlab.ui.control.NumericEditField
        TagLonEditFieldLabel           matlab.ui.control.Label
        TagLatEditField                matlab.ui.control.NumericEditField
        TagLatEditFieldLabel           matlab.ui.control.Label
        ActiveBearingButtonGroup       matlab.ui.container.ButtonGroup
        OffButton                      matlab.ui.control.RadioButton
        ClearButton                    matlab.ui.control.Button
        SaveButton                     matlab.ui.control.Button
        Button_3                       matlab.ui.control.RadioButton
        Button_2                       matlab.ui.control.RadioButton
        Button                         matlab.ui.control.RadioButton
        PlotPropertyButtonGroup        matlab.ui.container.ButtonGroup
        DivergenceButton               matlab.ui.control.RadioButton
        ValueButton                    matlab.ui.control.RadioButton
        SmoothingWindowEditField       matlab.ui.control.NumericEditField
        SmoothingWindowEditFieldLabel  matlab.ui.control.Label
        GridResmEditField              matlab.ui.control.NumericEditField
        GridResmEditFieldLabel         matlab.ui.control.Label
        EndTimesEditField              matlab.ui.control.NumericEditField
        EndTimesEditFieldLabel         matlab.ui.control.Label
        StartTimesEditField            matlab.ui.control.NumericEditField
        StartTimesEditFieldLabel       matlab.ui.control.Label
        ExportKMLButton                matlab.ui.control.Button
        PropertyDropDown               matlab.ui.control.DropDown
        PropertyDropDownLabel          matlab.ui.control.Label
        AxisDropDown                   matlab.ui.control.DropDown
        AxisDropDownLabel              matlab.ui.control.Label
        TagIDDropDown                  matlab.ui.control.DropDown
        TagIDDropDownLabel             matlab.ui.control.Label
        FileEditField                  matlab.ui.control.EditField
        FileEditFieldLabel             matlab.ui.control.Label
        LoadDataButton                 matlab.ui.control.Button
        RightPanel                     matlab.ui.container.Panel
        PlotGrid                       matlab.ui.container.GridLayout
        SNRRangeSlider                 matlab.ui.control.RangeSlider
        SNRRangeSliderLabel            matlab.ui.control.Label
        TimeSelectionminSlider         matlab.ui.control.RangeSlider
        TimeSelectionminSliderLabel    matlab.ui.control.Label
        UIAxes                         matlab.ui.control.UIAxes
    end

    % Properties that correspond to apps with auto-reflow
    properties (Access = private)
        onePanelWidth = 576;
        sidebarWidth  = 230;   % width of the control column, px
    end


    properties (Access = public)
        data            % Table of pulse records (canonical column names)
        currentBearing  % Bearing estimate for the current selection
        bearings        % Saved bearing estimates, one per Active Bearing radio button
        activeBearing = 0;
        takeoffElev = 0;% Elevation of the takeoff point, m MSL
    end

    properties (Access = private)
        fileName        % Source CSV name, no extension
        filePath        % Source CSV folder
        plotState       % Snapshot of the last plot, consumed by the KML export
        colorbarHandle  % Handle to the axes colorbar, so stale ones can be removed
    end

    methods (Access = private)

        % ---------------------------------------------------------------
        % Geodesy helpers.
        %
        % These replace latlon2local/local2latlon (Automated Driving
        % Toolbox) and wrapTo360 (Mapping Toolbox) so the app runs on a
        % bare MATLAB install. Same flat-earth approximation the toolbox
        % functions use: WGS84 meridional/normal radii evaluated at the
        % reference latitude. Good to well under a metre over the few
        % hundred metres a pulse survey covers.
        % ---------------------------------------------------------------

        % ---------------------------------------------------------------
        % CSV reader.
        %
        % TagTracker and MavlinkTagController2 have shipped four header
        % variants of the pulse log:
        %
        %   2023 builds     no header at all, 20 columns
        %   2024-2026-04    "# 7, tag_id, ... position_x, _y, _z, ..."   21 cols
        %   dev / master    "# 1, tag_id, ... latitude, longitude, altitude_rel, ..." 20 cols
        %
        % In every one of them the first 16 fields of a pulse record are
        % in the same order, and columns 14/15/16 are lat/lon/alt. The
        % full pulse log also interleaves 4-field rotation start/stop
        % records, which readtable would otherwise silently turn into
        % pulses with a latitude in the tag_id column.
        %
        % So: parse positionally, keep only rows with a full pulse
        % payload, and sanity check the geodetic fields.
        % ---------------------------------------------------------------

        function resetBearings(app)
            % One saved bearing per numbered radio button in the group.
            nSlots = numel(findobj(app.ActiveBearingButtonGroup, 'Type', 'uiradiobutton')) - 1;
            nSlots = max(nSlots, 3);
            emptyBearing = app.emptyBearingStruct();
            app.bearings = repmat(emptyBearing, 1, nSlots);
        end

        function slot = activeBearingSlot(app)
            % 0 when the group is on "Off"; the button number otherwise.
            selectedButton = app.ActiveBearingButtonGroup.SelectedObject;
            if isempty(selectedButton) || strcmp(selectedButton.Text, 'Off')
                slot = 0;
            else
                slot = str2double(selectedButton.Text);
                if ~isfinite(slot) || slot < 1 || slot > numel(app.bearings)
                    slot = 0;
                end
            end
        end

        function b = emptyBearingStruct(app)
            b.bearingDeg       = NaN;   % compass degrees, 0 = north, clockwise
            b.confidence       = NaN;   % 0..1 resultant length of the gradient field
            b.spreadDeg        = NaN;   % circular standard deviation
            b.tagID            = NaN;
            b.property         = '';
            b.pulseMask        = [];
            b.startPositionX   = [];
            b.startPositionY   = [];
            b.startPositionLon = [];
            b.startPositionLat = [];
        end
    end

    methods (Access = public)

        function updateAreaPlot(app)

            if isempty(app.data) || isempty(app.TagIDDropDown.Items)
                return
            end

            %% BUILD THE MASKS FOR THE PULSES WE WANT
            selectedTag = str2double(app.TagIDDropDown.Value);
            idMask      = app.data.tag_id == selectedTag;
            timeSec     = app.data.start_time_seconds - app.data.start_time_seconds(1);
            timeMask    = timeSec >= app.StartTimesEditField.Value & ...
                          timeSec <= app.EndTimesEditField.Value;
            snrMask     = app.data.snr >= app.SNRRangeSlider.Value(1) & ...
                          app.data.snr <= app.SNRRangeSlider.Value(2);
            totalMask   = idMask & timeMask & snrMask;
            dataMasked  = app.data(totalMask, :);

            latAll = app.data.lat;
            lonAll = app.data.lon;
            altAll = app.data.alt_rel;

            % Origin of the local ENU frame: the first pulse of the flight,
            % as before. Safe now that the reader drops records without a
            % valid fix, which previously could make this NaN.
            home = [latAll(1), lonAll(1), 0];

            [xEastAll, yNorthAll, ~] = geo2enu(latAll, lonAll, altAll, home);

            lat = dataMasked.lat;
            lon = dataMasked.lon;
            alt = dataMasked.alt_rel;
            [xEast, yNorth, zUp] = geo2enu(lat, lon, alt, home);

            useLonLat = strcmp(app.AxisDropDown.Value, 'Lon, Lat');

            %% LOAD THE PROPERTY OF INTEREST AS THE PROP VARIABLE
            switch app.PropertyDropDown.Value
                case 'SNR'
                    PROP = dataMasked.snr;
                case 'STFT Score'
                    PROP = dataMasked.stft_score;
                case 'Time'
                    PROP = timeSec(totalMask);
                case 'Altitude (m)'
                    PROP = zUp;
                otherwise
                    PROP = dataMasked.snr;
            end
            PROP = PROP(:);

            % SMOOTH THE PROPERTY USING MOVING MEAN
            smoothWin = app.SmoothingWindowEditField.Value;
            if smoothWin > 1 && ~isempty(PROP)
                PROP = movmean(PROP, smoothWin, 'omitnan');
            end

            % A property needs at least two distinct finite values before
            % any of the gridding, contouring or gradient work is meaningful.
            finitePROP  = PROP(isfinite(PROP));
            haveSurface = numel(finitePROP) > 3 && numel(unique(finitePROP)) > 1;

            %% DEFINE THE COLORMAP FOR THE POINTS TO BE PLOTTED
            colors = turbo(100);
            if isempty(PROP)
                pointColors = zeros(0, 3);
            elseif isempty(finitePROP) || numel(unique(finitePROP)) == 1
                pointColors = repmat(colors(end, :), numel(PROP), 1);
            else
                colorVals   = linspace(min(finitePROP), max(finitePROP), 100);
                clamped     = min(max(PROP, colorVals(1)), colorVals(end));
                pointColors = interp1(colorVals, colors, clamped);
                pointColors(~isfinite(pointColors)) = 0.5;
            end

            %% RESET THE AXES
            delete(app.colorbarHandle);
            app.colorbarHandle = gobjects(0);
            cla(app.UIAxes);
            hold(app.UIAxes, 'on');

            %% PLOT THE SCATTER PLOT OF ALL THE PULSES
            if useLonLat
                scatter(app.UIAxes, lonAll, latAll, 100, 0.8*[1 1 1], ...
                    'DisplayName', 'All pulses');
            else
                scatter(app.UIAxes, xEastAll, yNorthAll, 100, 0.8*[1 1 1], ...
                    'DisplayName', 'All pulses');
            end

            %% PLOT THE TAG POSITION IF ENABLED
            if strcmp(app.PlotTagSwitch.Value, 'On')
                if useLonLat
                    tagHoriz = app.TagLonEditField.Value;
                    tagVert  = app.TagLatEditField.Value;
                else
                    [tagHoriz, tagVert, ~] = geo2enu( ...
                        app.TagLatEditField.Value, app.TagLonEditField.Value, 0, home);
                end
                scatter(app.UIAxes, tagHoriz, tagVert, 500, [0 0 0], 'filled', 'hexagram', ...
                    'DisplayName', 'Tag');
            end

            %% BUILD THE INTERPOLATION GRID
            gridRes  = max(app.GridResmEditField.Value, 1);
            PROPGrid = [];
            X = []; Y = []; LAT = []; LON = [];

            if haveSurface
                % A 1 m grid over a multi-kilometre flight is millions of
                % cells and locks the UI up, so coarsen rather than hang.
                spanE = ceil(max(xEast))  - floor(min(xEast));
                spanN = ceil(max(yNorth)) - floor(min(yNorth));
                maxCells = 2e5;
                if (spanE/gridRes + 1)*(spanN/gridRes + 1) > maxCells
                    gridRes = max(gridRes, sqrt(spanE*spanN/maxCells));
                end
                xVec = floor(min(xEast)):gridRes:ceil(max(xEast));
                yVec = floor(min(yNorth)):gridRes:ceil(max(yNorth));
                if numel(xVec) > 1 && numel(yVec) > 1
                    [X, Y] = meshgrid(xVec, yVec);
                    [LAT, LON, ~] = enu2geo(X, Y, zeros(size(X)), home);
                    try
                        PROPGrid = griddata(xEast, yNorth, PROP, X, Y);
                    catch
                        % Collinear or degenerate point sets: no surface.
                        PROPGrid = [];
                    end
                end
            end
            haveSurface = ~isempty(PROPGrid) && any(isfinite(PROPGrid(:)));

            %% COMPUTE THE BEARING AND PLOT THE PROPERTY SURFACE
            bearing = app.emptyBearingStruct();
            bearing.tagID     = selectedTag;
            bearing.property  = app.PropertyDropDown.Value;
            bearing.pulseMask = totalMask;

            if haveSurface
                if useLonLat
                    HORIZ = LON;
                    VERT  = LAT;
                else
                    HORIZ = X;
                    VERT  = Y;
                end

                [FX, FY] = gradient(PROPGrid, gridRes);

                if strcmp(app.PlotPropertyButtonGroup.SelectedObject.Text, 'Divergence')
                    contourf(app.UIAxes, HORIZ, VERT, divergence(X, Y, FX, FY), ...
                        'DisplayName', 'Divergence');
                    colormap(app.UIAxes, 'parula');
                    app.colorbarHandle = colorbar(app.UIAxes);
                    app.colorbarHandle.Label.String = ...
                        ['div(grad ', app.PropertyDropDown.Value, ')'];
                else
                    contourf(app.UIAxes, HORIZ, VERT, PROPGrid, 'FaceAlpha', 0.6, ...
                        'DisplayName', 'Interpolated PROP Map');
                    colormap(app.UIAxes, 'turbo');
                    app.colorbarHandle = colorbar(app.UIAxes);
                    app.colorbarHandle.Label.String = app.PropertyDropDown.Value;
                end

                % ---------------------------------------------------------
                % Bearing estimate.
                %
                % The gradient of the interpolated property points uphill,
                % i.e. towards the tag. This takes the magnitude-weighted
                % circular mean of the gradient directions. Note that the
                % weight cancels the unit-vector normalisation - w.*ux is
                % just fx - so the resultant is the plain vector sum and the
                % reported DIRECTION is exactly what averaging FX and FY
                % would give. What the circular form adds is the confidence
                % below, which a component average has no counterpart for.
                % Cells outside the convex hull of the data are NaN in
                % PROPGrid and are excluded rather than being averaged in.
                %
                % confidence is the resultant length: 1 means every cell
                % points the same way, 0 means the field has no consensus.
                % spreadDeg is the matching circular standard deviation.
                % ---------------------------------------------------------
                valid = isfinite(FX) & isfinite(FY);
                fxV   = FX(valid);
                fyV   = FY(valid);
                w     = hypot(fxV, fyV);
                sel   = w > 0;
                if any(sel)
                    ux = fxV(sel)./w(sel);
                    uy = fyV(sel)./w(sel);
                    w  = w(sel);

                    Rx = sum(w.*ux);
                    Ry = sum(w.*uy);
                    W  = sum(w);

                    mathDeg           = atan2d(Ry, Rx);
                    bearing.bearingDeg = mod(90 - mathDeg, 360);
                    bearing.confidence = min(hypot(Rx, Ry)/W, 1);
                    bearing.spreadDeg  = sqrt(max(-2*log(max(bearing.confidence, eps)), 0))*180/pi;
                end

                bearing.startPositionX   = mean(xEast, 'omitnan');
                bearing.startPositionY   = mean(yNorth, 'omitnan');
                [bearing.startPositionLat, bearing.startPositionLon, ~] = ...
                    enu2geo(bearing.startPositionX, bearing.startPositionY, 0, home);
            end

            app.currentBearing = bearing;

            if isnan(bearing.bearingDeg)
                app.BearingEditField.Value    = '-';
                app.ConfidenceEditField.Value = '-';
                app.SpreadEditField.Value     = '-';
            else
                app.BearingEditField.Value    = sprintf('%.1f', bearing.bearingDeg);
                app.ConfidenceEditField.Value = sprintf('%.2f', bearing.confidence);
                app.SpreadEditField.Value     = sprintf('%.0f', bearing.spreadDeg);
            end

            %% AXIS SCALING AND LABELS
            % In Lon/Lat mode a degree of longitude is shorter than a degree
            % of latitude, so 'axis equal' would stretch the map east-west.
            if useLonLat
                xlabel(app.UIAxes, 'Longitude (deg)');
                ylabel(app.UIAxes, 'Latitude (deg)');
                daspect(app.UIAxes, [1 cosd(home(1)) 1]);
            else
                xlabel(app.UIAxes, 'X-position, East (m)');
                ylabel(app.UIAxes, 'Y-position, North (m)');
                daspect(app.UIAxes, [1 1 1]);
            end
            grid(app.UIAxes, 'on');

            spanX = diff(app.UIAxes.XLim);
            spanY = diff(app.UIAxes.YLim);
            minPlotSpan = min(spanX, spanY);
            if ~isfinite(minPlotSpan) || minPlotSpan <= 0
                minPlotSpan = 1;
            end
            quiverFactor = 0.2*minPlotSpan;

            %% PLOT THE CURRENT AND SAVED BEARINGS
            % bearingDeg is stored in compass degrees, so the east/north
            % components are sin/cos of it. In Lon/Lat mode the east
            % component has to be divided by cos(latitude) to stay a true
            % compass direction on a degrees-vs-degrees axis.
            lonScale = 1;
            if useLonLat
                lonScale = 1/cosd(home(1));
            end

            allBearings = [app.currentBearing, app.bearings(:).'];
            styles      = [{'--'}, repmat({'-'}, 1, numel(app.bearings))];
            for i = 1:numel(allBearings)
                b = allBearings(i);
                if isnan(b.bearingDeg) || isempty(b.startPositionX)
                    continue
                end
                fx = sind(b.bearingDeg)*lonScale;
                fy = cosd(b.bearingDeg);
                if useLonLat
                    horiz = b.startPositionLon;
                    vert  = b.startPositionLat;
                else
                    horiz = b.startPositionX;
                    vert  = b.startPositionY;
                end
                quiver(app.UIAxes, horiz, vert, quiverFactor*fx, quiverFactor*fy, 1, ...
                    styles{i}, 'Color', [0.3 0.3 0.3], 'LineWidth', 1.5, ...
                    'MaxHeadSize', 1, 'DisplayName', 'Calculated Bearing');
            end

            %% PLOT THE SCATTER PLOT OF THE SELECTED PULSES
            if ~isempty(PROP)
                if useLonLat
                    scatter(app.UIAxes, lon, lat, 100, pointColors, 'filled', ...
                        'DisplayName', 'Selected pulses');
                else
                    scatter(app.UIAxes, xEast, yNorth, 100, pointColors, 'filled', ...
                        'DisplayName', 'Selected pulses');
                end
            end

            hold(app.UIAxes, 'off');

            %% TITLE
            if isnan(bearing.bearingDeg)
                bearingText = 'bearing n/a';
            else
                bearingText = sprintf('bearing %.1f\\circ (conf %.2f, \\pm%.0f\\circ)', ...
                    bearing.bearingDeg, bearing.confidence, bearing.spreadDeg);
            end
            % Two lines: one long title runs off the ends of a narrow axes.
            title(app.UIAxes, { ...
                sprintf('Tag %s  |  %s  |  %d of %d pulses', ...
                    app.TagIDDropDown.Value, app.PropertyDropDown.Value, ...
                    height(dataMasked), height(app.data)), ...
                bearingText}, ...
                'Interpreter', 'tex');

            %% SNAPSHOT THE STATE THE KML EXPORT NEEDS
            % Building the KML here would rebuild every placemark on every
            % slider drag, which is what made the app crawl on long flights.
            % Export does the work instead.
            app.plotState = struct( ...
                'lat',         lat, ...
                'lon',         lon, ...
                'altAbs',      zUp + app.takeoffElev, ...
                'PROP',        PROP, ...
                'GRIDLAT',     LAT, ...
                'GRIDLON',     LON, ...
                'PROPGrid',    PROPGrid, ...
                'property',    app.PropertyDropDown.Value, ...
                'tagID',       app.TagIDDropDown.Value, ...
                'plotTag',     strcmp(app.PlotTagSwitch.Value, 'On'), ...
                'tagLat',      app.TagLatEditField.Value, ...
                'tagLon',      app.TagLonEditField.Value);
        end
    end

    % Callbacks that handle component events
    methods (Access = private)

        % Code that executes after component creation
        function startupFcn(app)
            app.resetBearings();
            app.currentBearing = app.emptyBearingStruct();
            app.colorbarHandle = gobjects(0);
            title(app.UIAxes, 'Load a pulse CSV to begin');
        end

        % Button pushed function: LoadDataButton
        function LoadDataButtonPushed(app, event)
            [file, location] = uigetfile('*.csv', 'Select CSV Pulse Log');
            if isequal(file, 0)
                return      % user cancelled
            end
            fullFilePath = fullfile(location, file);

            try
                [newData, warnMsg] = readpulsetable(fullFilePath);
            catch ME
                uialert(app.UIFigure, ME.message, 'Could not read pulse log');
                return
            end
            if ~isempty(warnMsg)
                uialert(app.UIFigure, warnMsg, 'Pulse log warning', 'Icon', 'warning');
            end

            [app.filePath, app.fileName, ~] = fileparts(fullFilePath);
            app.FileEditField.Value = app.fileName;
            app.data = newData;

            % A new flight invalidates anything saved against the old one.
            app.resetBearings();
            app.currentBearing = app.emptyBearingStruct();
            app.plotState    = [];

            %UPDATE DROP DOWN WITH ID VALUES
            idOptions = unique(app.data.tag_id);
            n = numel(idOptions);
            tagIDsStringCell = cell(1, n);
            for i = 1:n
                tagIDsStringCell{i} = num2str(idOptions(i));
            end
            app.TagIDDropDown.Items = tagIDsStringCell;

            %Set tag id to the most prevalent in the dataset
            app.TagIDDropDown.Value = num2str(mode(app.data.tag_id));

            %TIME SLIDER
            timeMin  = (app.data.start_time_seconds - app.data.start_time_seconds(1))/60;
            minTime  = min(timeMin);
            maxTime  = max(timeMin);
            if maxTime <= minTime
                maxTime = minTime + eps(minTime) + 1/60;   % single-pulse logs
            end
            app.TimeSelectionminSlider.Limits = [minTime, maxTime];
            app.TimeSelectionminSlider.Value  = [minTime, maxTime];

            totalTime = maxTime - minTime;
            major = totalTime/10;
            minor = totalTime/50;
            if major > 0
                majorTicks = minTime:major:maxTime;
                app.TimeSelectionminSlider.MajorTicks = majorTicks;
                app.TimeSelectionminSlider.MajorTickLabels = ...
                    arrayfun(@(v) sprintf('%.1f', v), majorTicks, 'UniformOutput', false);
                app.TimeSelectionminSlider.MinorTicks = minTime:minor:maxTime;
            end

            %SNR SLIDER
            snrMin = min(app.data.snr);
            snrMax = max(app.data.snr);
            if ~isfinite(snrMin) || ~isfinite(snrMax)
                snrMin = 0; snrMax = 1;
            end
            if snrMax <= snrMin
                snrMax = snrMin + 1;    % Limits must be strictly increasing
            end
            app.SNRRangeSlider.Limits = [snrMin, snrMax];
            app.SNRRangeSlider.Value  = [snrMin, snrMax];
            snrStep = max(round((snrMax - snrMin)/10), 1);
            snrTicks = snrMin:snrStep:snrMax;
            app.SNRRangeSlider.MajorTicks = snrTicks;
            app.SNRRangeSlider.MajorTickLabels = ...
                arrayfun(@(v) sprintf('%.0f', v), snrTicks, 'UniformOutput', false);
            app.SNRRangeSlider.MinorTicks = snrTicks;

            % Set the edit fields from the slider before the first plot.
            app.StartTimesEditField.Value = minTime*60;
            app.EndTimesEditField.Value   = maxTime*60;

            % Takeoff elevation comes from the Elev (m) field rather than a
            % modal legacy dialog, which blocks a uifigure app from behind.
            % A field can also be corrected without reloading the log.
            app.takeoffElev = app.TakeoffElevEditField.Value;

            updateAreaPlot(app);
        end

        % Value changed function: TimeSelectionminSlider
        function TimeSelectionminSliderValueChanged(app, event)
            value = app.TimeSelectionminSlider.Value;
            app.StartTimesEditField.Value = value(1)*60;
            app.EndTimesEditField.Value   = value(2)*60;
            updateAreaPlot(app)
        end

        % Value changed function: SmoothingWindowEditField
        function SmoothingWindowEditFieldValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: GridResmEditField
        function GridResmEditFieldValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Selection changed function: PlotPropertyButtonGroup
        function PlotPropertyButtonGroupSelectionChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: AxisDropDown
        function AxisDropDownValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: PropertyDropDown
        function PropertyDropDownValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: SNRRangeSlider
        function SNRRangeSliderValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: TakeoffElevEditField
        function TakeoffElevEditFieldValueChanged(app, event)
            app.takeoffElev = app.TakeoffElevEditField.Value;
            updateAreaPlot(app)
        end

        % Value changed function: TagLatEditField, TagLonEditField
        function TagPositionValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Button pushed function: ExportKMLButton
        function ExportKMLButtonPushed(app, event)
            if isempty(app.plotState) || isempty(app.data)
                uialert(app.UIFigure, 'Load a pulse log and plot it before exporting.', ...
                    'Nothing to export');
                return
            end

            s = app.plotState;
            defaultName = [app.fileName, '_', matlab.lang.makeValidName(s.property), '_KML.kmz'];
            [file, location] = uiputfile('*.kmz', 'Save KMZ', fullfile(app.filePath, defaultName));
            if isequal(file, 0)
                return
            end

            dlg = uiprogressdlg(app.UIFigure, 'Title', 'Export KMZ', ...
                'Message', 'Writing KMZ...', 'Indeterminate', 'on');
            cleanup = onCleanup(@() close(dlg)); %#ok<NASGU>

            try
                args = {};
                if ~isempty(s.PROPGrid)
                    args = [args, {'GridLat', s.GRIDLAT, 'GridLon', s.GRIDLON, ...
                                   'GridValue', s.PROPGrid}];
                end
                if ~isempty(s.PROP)
                    args = [args, {'PointLat', s.lat, 'PointLon', s.lon, ...
                                   'PointAlt', s.altAbs, 'PointValue', s.PROP, ...
                                   'PointAltitudeMode', 'absolute', ...
                                   'PointFolderName', ['Pulses (tag ', s.tagID, ')']}];
                end
                if s.plotTag
                    args = [args, {'MarkerLat', s.tagLat, 'MarkerLon', s.tagLon, ...
                                   'MarkerName', 'Tag', 'MarkerFolderName', 'Tag'}];
                end
                kmzwrite(fullfile(location, file), ...
                    'Name',        app.fileName, ...
                    'Description', ['Tag ', s.tagID, ', ', s.property], ...
                    'ValueName',   s.property, ...
                    args{:});
            catch ME
                uialert(app.UIFigure, ME.message, 'KMZ export failed');
            end
        end

        % Selection changed function: ActiveBearingButtonGroup
        function ActiveBearingButtonGroupSelectionChanged(app, event)
            app.activeBearing = app.activeBearingSlot();
        end

        % Button pushed function: SaveButton
        function SaveButtonPushed(app, event)
            slot = app.activeBearingSlot();
            if slot == 0
                uialert(app.UIFigure, ...
                    'Select bearing slot 1, 2 or 3 before saving.', 'No bearing slot selected');
                return
            end
            if isnan(app.currentBearing.bearingDeg)
                uialert(app.UIFigure, ...
                    'There is no bearing to save for the current selection.', 'No bearing');
                return
            end
            app.bearings(slot) = app.currentBearing;
            updateAreaPlot(app);
        end

        % Button pushed function: ClearButton
        function ClearButtonPushed(app, event)
            slot = app.activeBearingSlot();
            if slot == 0
                uialert(app.UIFigure, ...
                    'Select bearing slot 1, 2 or 3 before clearing.', 'No bearing slot selected');
                return
            end
            app.bearings(slot) = app.emptyBearingStruct();
            updateAreaPlot(app);
        end

        % Value changed function: PlotTagSwitch
        function PlotTagSwitchValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Value changed function: TagIDDropDown
        function TagIDDropDownValueChanged(app, event)
            updateAreaPlot(app)
        end

        % Changes arrangement of the app based on UIFigure width
        function updateAppLayout(app, event)
            currentFigureWidth = app.UIFigure.Position(3);
            if currentFigureWidth <= app.onePanelWidth
                % Too narrow for side by side: stack the control column above
                % the plot. The column keeps a fixed height and scrolls
                % internally, so none of its controls are lost.
                app.GridLayout.RowHeight   = {320, '1x'};
                app.GridLayout.ColumnWidth = {'1x'};
                app.LeftPanel.Layout.Row      = 1;
                app.LeftPanel.Layout.Column   = 1;
                app.RightPanel.Layout.Row     = 2;
                app.RightPanel.Layout.Column  = 1;
            else
                app.GridLayout.RowHeight   = {'1x'};
                app.GridLayout.ColumnWidth = {app.sidebarWidth, '1x'};
                app.LeftPanel.Layout.Row      = 1;
                app.LeftPanel.Layout.Column   = 1;
                app.RightPanel.Layout.Row     = 1;
                app.RightPanel.Layout.Column  = 2;
            end
        end
    end

    % Component initialization
    methods (Access = private)

        % ---------------------------------------------------------------
        % Layout helpers.
        %
        % The window is built from nested uigridlayout containers rather
        % than absolute Position vectors. Absolute positions are what made
        % the original layout fragile: shrinking the figure pushed the top
        % of the control column off the panel and squeezed the range
        % sliders under the axes, and MATLAB gives no warning when it does
        % either. A grid cannot overlap or clip its cells, and the control
        % column is Scrollable, so a short window scrolls rather than
        % hiding the controls at the bottom.
        %
        % The one place absolute positions survive is inside the two
        % button groups, because uiradiobutton must be a direct child of
        % its ButtonGroup and cannot be placed in a grid. Those groups sit
        % in fixed-size grid cells and have AutoResizeChildren off, so
        % their contents never move.
        % ---------------------------------------------------------------

        function [row, heights] = addSection(app, parent, row, heights, text) %#ok<INUSD>
            % Bold caption over a hairline rule. Mirrors the Python port.
            row = row + 1;
            heights{row} = 22;
            header = uilabel(parent);
            header.Text = text;
            header.FontWeight = 'bold';
            header.FontColor = [0.29 0.33 0.41];
            header.VerticalAlignment = 'bottom';
            header.Layout.Row = row;
            header.Layout.Column = [1 2];

            row = row + 1;
            heights{row} = 1;
            rule = uipanel(parent);
            rule.BorderType = 'none';
            rule.BackgroundColor = [0.80 0.80 0.82];
            rule.Layout.Row = row;
            rule.Layout.Column = [1 2];
        end

        function label = addLabel(app, parent, row, text) %#ok<INUSD>
            % Right-aligned caption in the first column of a control row.
            label = uilabel(parent);
            label.Text = text;
            label.HorizontalAlignment = 'right';
            label.Layout.Row = row;
            label.Layout.Column = 1;
        end

        function [field, label] = addReadout(app, parent, row, text)
            % Read-only text field. Text rather than numeric so that "no
            % value yet" can show as a dash instead of -Inf.
            label = app.addLabel(parent, row, text);
            field = uieditfield(parent, 'text');
            field.Editable = 'off';
            field.HorizontalAlignment = 'right';
            field.Value = '-';
            field.Layout.Row = row;
            field.Layout.Column = 2;
        end

        % Create UIFigure and components
        function createComponents(app)

            % Create UIFigure and hide until all components are created
            app.UIFigure = uifigure('Visible', 'off');
            app.UIFigure.AutoResizeChildren = 'off';
            app.UIFigure.Position = [100 100 1000 700];
            app.UIFigure.Name = 'pulseplotter';
            app.UIFigure.SizeChangedFcn = createCallbackFcn(app, @updateAppLayout, true);

            % Create GridLayout
            app.GridLayout = uigridlayout(app.UIFigure);
            app.GridLayout.ColumnWidth = {app.sidebarWidth, '1x'};
            app.GridLayout.RowHeight = {'1x'};
            app.GridLayout.ColumnSpacing = 0;
            app.GridLayout.RowSpacing = 0;
            app.GridLayout.Padding = [0 0 0 0];

            % Create LeftPanel
            app.LeftPanel = uipanel(app.GridLayout);
            app.LeftPanel.Layout.Row = 1;
            app.LeftPanel.Layout.Column = 1;

            % Create ControlGrid - the scrolling control column.
            % Every row has a fixed height; that is what lets Scrollable
            % work out how tall the contents are and scroll when the
            % window is shorter than they need.
            app.ControlGrid = uigridlayout(app.LeftPanel);
            app.ControlGrid.ColumnWidth = {92, '1x'};
            app.ControlGrid.ColumnSpacing = 8;
            app.ControlGrid.RowSpacing = 4;
            app.ControlGrid.Padding = [10 10 10 10];
            app.ControlGrid.Scrollable = 'on';
            % Start with more rows than the column needs, so every
            % Layout.Row assignment below lands in a row that already
            % exists; the exact heights are applied once at the end.
            app.ControlGrid.RowHeight = repmat({22}, 1, 40);

            % Rows are numbered as they are created and their heights
            % collected alongside, so adding or moving a control cannot
            % put the two out of step.
            row = 0;
            heights = {};

            % ---- Load / Export -------------------------------------
            row = row + 1;
            heights{row} = 24;
            buttonRow = uigridlayout(app.ControlGrid);
            buttonRow.ColumnWidth = {'1x', '1x'};
            buttonRow.RowHeight = {'1x'};
            buttonRow.ColumnSpacing = 6;
            buttonRow.Padding = [0 0 0 0];
            buttonRow.Layout.Row = row;
            buttonRow.Layout.Column = [1 2];

            app.LoadDataButton = uibutton(buttonRow, 'push');
            app.LoadDataButton.ButtonPushedFcn = createCallbackFcn(app, @LoadDataButtonPushed, true);
            app.LoadDataButton.Text = 'Load Data';
            app.LoadDataButton.Layout.Row = 1;
            app.LoadDataButton.Layout.Column = 1;

            app.ExportKMLButton = uibutton(buttonRow, 'push');
            app.ExportKMLButton.ButtonPushedFcn = createCallbackFcn(app, @ExportKMLButtonPushed, true);
            app.ExportKMLButton.Text = 'Export KML';
            app.ExportKMLButton.Layout.Row = 1;
            app.ExportKMLButton.Layout.Column = 2;

            % ---- File ----------------------------------------------
            row = row + 1;
            heights{row} = 22;
            app.FileEditFieldLabel = app.addLabel(app.ControlGrid, row, 'File');
            app.FileEditField = uieditfield(app.ControlGrid, 'text');
            app.FileEditField.Editable = 'off';
            app.FileEditField.Layout.Row = row;
            app.FileEditField.Layout.Column = 2;

            % ---- Data selection ------------------------------------
            [row, heights] = app.addSection(app.ControlGrid, row, heights, 'Data selection');

            row = row + 1;
            heights{row} = 22;
            app.TagIDDropDownLabel = app.addLabel(app.ControlGrid, row, 'Tag ID');
            app.TagIDDropDown = uidropdown(app.ControlGrid);
            app.TagIDDropDown.Items = {};
            app.TagIDDropDown.ValueChangedFcn = createCallbackFcn(app, @TagIDDropDownValueChanged, true);
            app.TagIDDropDown.Value = {};
            app.TagIDDropDown.Layout.Row = row;
            app.TagIDDropDown.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.AxisDropDownLabel = app.addLabel(app.ControlGrid, row, 'Axis');
            app.AxisDropDown = uidropdown(app.ControlGrid);
            app.AxisDropDown.Items = {'x, y', 'Lon, Lat'};
            app.AxisDropDown.ValueChangedFcn = createCallbackFcn(app, @AxisDropDownValueChanged, true);
            app.AxisDropDown.Value = 'x, y';
            app.AxisDropDown.Layout.Row = row;
            app.AxisDropDown.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.PropertyDropDownLabel = app.addLabel(app.ControlGrid, row, 'Property');
            app.PropertyDropDown = uidropdown(app.ControlGrid);
            app.PropertyDropDown.Items = {'SNR', 'STFT Score', 'Time', 'Altitude (m)'};
            app.PropertyDropDown.ValueChangedFcn = createCallbackFcn(app, @PropertyDropDownValueChanged, true);
            app.PropertyDropDown.Value = 'SNR';
            app.PropertyDropDown.Layout.Row = row;
            app.PropertyDropDown.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.StartTimesEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Start Time (s)');
            app.StartTimesEditField = uieditfield(app.ControlGrid, 'numeric');
            app.StartTimesEditField.Editable = 'off';
            app.StartTimesEditField.HorizontalAlignment = 'right';
            app.StartTimesEditField.Layout.Row = row;
            app.StartTimesEditField.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.EndTimesEditFieldLabel = app.addLabel(app.ControlGrid, row, 'End Time (s)');
            app.EndTimesEditField = uieditfield(app.ControlGrid, 'numeric');
            app.EndTimesEditField.Editable = 'off';
            app.EndTimesEditField.HorizontalAlignment = 'right';
            app.EndTimesEditField.Layout.Row = row;
            app.EndTimesEditField.Layout.Column = 2;

            % ---- Surface -------------------------------------------
            [row, heights] = app.addSection(app.ControlGrid, row, heights, 'Surface');

            row = row + 1;
            heights{row} = 22;
            app.SmoothingWindowEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Smoothing');
            app.SmoothingWindowEditField = uieditfield(app.ControlGrid, 'numeric');
            app.SmoothingWindowEditField.Limits = [0 10];
            app.SmoothingWindowEditField.RoundFractionalValues = 'on';
            app.SmoothingWindowEditField.ValueDisplayFormat = '%11.0g';
            app.SmoothingWindowEditField.HorizontalAlignment = 'right';
            app.SmoothingWindowEditField.ValueChangedFcn = createCallbackFcn(app, @SmoothingWindowEditFieldValueChanged, true);
            app.SmoothingWindowEditField.Tooltip = {'Moving-mean window over the property, in pulses. 0 or 1 disables it.'};
            app.SmoothingWindowEditField.Value = 6;
            app.SmoothingWindowEditField.Layout.Row = row;
            app.SmoothingWindowEditField.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.GridResmEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Grid Res. (m)');
            app.GridResmEditField = uieditfield(app.ControlGrid, 'numeric');
            app.GridResmEditField.Limits = [1 50];
            app.GridResmEditField.RoundFractionalValues = 'on';
            app.GridResmEditField.ValueDisplayFormat = '%11.0g';
            app.GridResmEditField.HorizontalAlignment = 'right';
            app.GridResmEditField.ValueChangedFcn = createCallbackFcn(app, @GridResmEditFieldValueChanged, true);
            app.GridResmEditField.Tooltip = {'Interpolation grid spacing in metres.'};
            app.GridResmEditField.Value = 5;
            app.GridResmEditField.Layout.Row = row;
            app.GridResmEditField.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.TakeoffElevEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Elev (m)');
            app.TakeoffElevEditField = uieditfield(app.ControlGrid, 'numeric');
            app.TakeoffElevEditField.HorizontalAlignment = 'right';
            app.TakeoffElevEditField.ValueChangedFcn = createCallbackFcn(app, @TakeoffElevEditFieldValueChanged, true);
            app.TakeoffElevEditField.Tooltip = {'Elevation of the takeoff point in metres MSL. Added to the relative pulse altitudes when writing KML.'};
            app.TakeoffElevEditField.Value = 0;
            app.TakeoffElevEditField.Layout.Row = row;
            app.TakeoffElevEditField.Layout.Column = 2;

            % Plot Property. Borderless and untitled: the section header
            % above already names the group, and a second nested border
            % just adds visual noise.
            row = row + 1;
            heights{row} = 24;
            app.PlotPropertyButtonGroup = uibuttongroup(app.ControlGrid);
            app.PlotPropertyButtonGroup.SelectionChangedFcn = createCallbackFcn(app, @PlotPropertyButtonGroupSelectionChanged, true);
            app.PlotPropertyButtonGroup.BorderType = 'none';
            app.PlotPropertyButtonGroup.Title = '';
            app.PlotPropertyButtonGroup.AutoResizeChildren = 'off';
            app.PlotPropertyButtonGroup.Layout.Row = row;
            app.PlotPropertyButtonGroup.Layout.Column = [1 2];

            plotPropertyCaption = uilabel(app.PlotPropertyButtonGroup);
            plotPropertyCaption.Text = 'Plot';
            plotPropertyCaption.HorizontalAlignment = 'left';
            plotPropertyCaption.Position = [0 1 32 22];

            app.ValueButton = uiradiobutton(app.PlotPropertyButtonGroup);
            app.ValueButton.Text = 'Value';
            app.ValueButton.Position = [38 1 62 22];
            app.ValueButton.Value = true;

            app.DivergenceButton = uiradiobutton(app.PlotPropertyButtonGroup);
            app.DivergenceButton.Text = 'Divergence';
            app.DivergenceButton.Position = [104 1 95 22];

            % ---- Tag position --------------------------------------
            [row, heights] = app.addSection(app.ControlGrid, row, heights, 'Tag position');

            row = row + 1;
            heights{row} = 22;
            app.TagLatEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Tag Lat');
            app.TagLatEditField = uieditfield(app.ControlGrid, 'numeric');
            app.TagLatEditField.ValueDisplayFormat = '%11.8g';
            app.TagLatEditField.HorizontalAlignment = 'right';
            app.TagLatEditField.ValueChangedFcn = createCallbackFcn(app, @TagPositionValueChanged, true);
            app.TagLatEditField.Layout.Row = row;
            app.TagLatEditField.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            app.TagLonEditFieldLabel = app.addLabel(app.ControlGrid, row, 'Tag Lon');
            app.TagLonEditField = uieditfield(app.ControlGrid, 'numeric');
            app.TagLonEditField.ValueDisplayFormat = '%11.8g';
            app.TagLonEditField.HorizontalAlignment = 'right';
            app.TagLonEditField.ValueChangedFcn = createCallbackFcn(app, @TagPositionValueChanged, true);
            app.TagLonEditField.Layout.Row = row;
            app.TagLonEditField.Layout.Column = 2;

            row = row + 1;
            heights{row} = 28;
            app.PlotTagSwitchLabel = app.addLabel(app.ControlGrid, row, 'Plot Tag');
            app.PlotTagSwitch = uiswitch(app.ControlGrid, 'slider');
            app.PlotTagSwitch.ValueChangedFcn = createCallbackFcn(app, @PlotTagSwitchValueChanged, true);
            app.PlotTagSwitch.Layout.Row = row;
            app.PlotTagSwitch.Layout.Column = 2;

            % ---- Bearing -------------------------------------------
            [row, heights] = app.addSection(app.ControlGrid, row, heights, 'Bearing');

            row = row + 1;
            heights{row} = 24;
            app.ActiveBearingButtonGroup = uibuttongroup(app.ControlGrid);
            app.ActiveBearingButtonGroup.SelectionChangedFcn = createCallbackFcn(app, @ActiveBearingButtonGroupSelectionChanged, true);
            app.ActiveBearingButtonGroup.BorderType = 'none';
            app.ActiveBearingButtonGroup.Title = '';
            app.ActiveBearingButtonGroup.AutoResizeChildren = 'off';
            app.ActiveBearingButtonGroup.Layout.Row = row;
            app.ActiveBearingButtonGroup.Layout.Column = [1 2];

            activeBearingCaption = uilabel(app.ActiveBearingButtonGroup);
            activeBearingCaption.Text = 'Active';
            activeBearingCaption.HorizontalAlignment = 'left';
            activeBearingCaption.Position = [0 1 40 22];

            app.OffButton = uiradiobutton(app.ActiveBearingButtonGroup);
            app.OffButton.Text = 'Off';
            app.OffButton.Position = [46 1 44 22];
            app.OffButton.Value = true;

            app.Button = uiradiobutton(app.ActiveBearingButtonGroup);
            app.Button.Text = '1';
            app.Button.Position = [94 1 32 22];

            app.Button_2 = uiradiobutton(app.ActiveBearingButtonGroup);
            app.Button_2.Text = '2';
            app.Button_2.Position = [130 1 32 22];

            app.Button_3 = uiradiobutton(app.ActiveBearingButtonGroup);
            app.Button_3.Text = '3';
            app.Button_3.Position = [166 1 32 22];

            row = row + 1;
            heights{row} = 24;
            bearingActions = uigridlayout(app.ControlGrid);
            bearingActions.ColumnWidth = {'1x', '1x'};
            bearingActions.RowHeight = {'1x'};
            bearingActions.ColumnSpacing = 6;
            bearingActions.Padding = [0 0 0 0];
            bearingActions.Layout.Row = row;
            bearingActions.Layout.Column = [1 2];

            app.SaveButton = uibutton(bearingActions, 'push');
            app.SaveButton.ButtonPushedFcn = createCallbackFcn(app, @SaveButtonPushed, true);
            app.SaveButton.Text = 'Save';
            app.SaveButton.Layout.Row = 1;
            app.SaveButton.Layout.Column = 1;

            app.ClearButton = uibutton(bearingActions, 'push');
            app.ClearButton.ButtonPushedFcn = createCallbackFcn(app, @ClearButtonPushed, true);
            app.ClearButton.Text = 'Clear';
            app.ClearButton.Layout.Row = 1;
            app.ClearButton.Layout.Column = 2;

            row = row + 1;
            heights{row} = 22;
            [app.BearingEditField, app.BearingEditFieldLabel] = ...
                app.addReadout(app.ControlGrid, row, 'Bearing (deg)');

            row = row + 1;
            heights{row} = 22;
            [app.ConfidenceEditField, app.ConfidenceEditFieldLabel] = ...
                app.addReadout(app.ControlGrid, row, 'Confidence');

            row = row + 1;
            heights{row} = 22;
            [app.SpreadEditField, app.SpreadEditFieldLabel] = ...
                app.addReadout(app.ControlGrid, row, 'Spread (deg)');

            app.ControlGrid.RowHeight = heights;

            % Create RightPanel
            app.RightPanel = uipanel(app.GridLayout);
            app.RightPanel.Layout.Row = 1;
            app.RightPanel.Layout.Column = 2;

            % Create PlotGrid. The axes are the only row that gives up
            % space, so the two range sliders always keep their height
            % instead of being pushed off the bottom of the panel.
            app.PlotGrid = uigridlayout(app.RightPanel);
            app.PlotGrid.ColumnWidth = {70, '1x'};
            app.PlotGrid.RowHeight = {'1x', 62, 62};
            app.PlotGrid.RowSpacing = 6;
            app.PlotGrid.ColumnSpacing = 8;
            app.PlotGrid.Padding = [8 10 14 8];

            % Create UIAxes
            app.UIAxes = uiaxes(app.PlotGrid);
            title(app.UIAxes, 'Title')
            xlabel(app.UIAxes, 'X')
            ylabel(app.UIAxes, 'Y')
            zlabel(app.UIAxes, 'Z')
            app.UIAxes.Layout.Row = 1;
            app.UIAxes.Layout.Column = [1 2];

            % Create TimeSelectionminSliderLabel
            app.TimeSelectionminSliderLabel = uilabel(app.PlotGrid);
            app.TimeSelectionminSliderLabel.HorizontalAlignment = 'right';
            app.TimeSelectionminSliderLabel.WordWrap = 'on';
            app.TimeSelectionminSliderLabel.Text = 'Time Selection (min)';
            app.TimeSelectionminSliderLabel.Layout.Row = 2;
            app.TimeSelectionminSliderLabel.Layout.Column = 1;

            % Create TimeSelectionminSlider
            app.TimeSelectionminSlider = uislider(app.PlotGrid, 'range');
            app.TimeSelectionminSlider.ValueChangedFcn = createCallbackFcn(app, @TimeSelectionminSliderValueChanged, true);
            app.TimeSelectionminSlider.Layout.Row = 2;
            app.TimeSelectionminSlider.Layout.Column = 2;

            % Create SNRRangeSliderLabel
            app.SNRRangeSliderLabel = uilabel(app.PlotGrid);
            app.SNRRangeSliderLabel.HorizontalAlignment = 'right';
            app.SNRRangeSliderLabel.WordWrap = 'on';
            app.SNRRangeSliderLabel.Text = 'SNR Range';
            app.SNRRangeSliderLabel.Layout.Row = 3;
            app.SNRRangeSliderLabel.Layout.Column = 1;

            % Create SNRRangeSlider
            app.SNRRangeSlider = uislider(app.PlotGrid, 'range');
            app.SNRRangeSlider.ValueChangedFcn = createCallbackFcn(app, @SNRRangeSliderValueChanged, true);
            app.SNRRangeSlider.Layout.Row = 3;
            app.SNRRangeSlider.Layout.Column = 2;

            % Show the figure after all components are created
            app.UIFigure.Visible = 'on';
        end
    end

    % App creation and deletion
    methods (Access = public)

        % Construct app
        function app = pulseplotter2

            % Create UIFigure and components
            createComponents(app)

            % Register the app with App Designer
            registerApp(app, app.UIFigure)

            % Execute the startup function
            runStartupFcn(app, @startupFcn)

            if nargout == 0
                clear app
            end
        end

        % Code that executes before app deletion
        function delete(app)

            % Delete UIFigure when app is deleted
            delete(app.UIFigure)
        end
    end
end
