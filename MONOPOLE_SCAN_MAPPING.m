
% data = readtable('/Users/mshafer/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA/2024-10-11-Ramond_Park_Monopole_Testing/HERELINK CONTROLLER LOGS/Pulse Log Files/Pulse-2024-10-11-15-25-35-497.csv');
%data = readtable('/Users/mshafer/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA/2025-01-03-Egr_Lawn_Mower_Scan_with_Hanging_Monopole/Pulse-2025-01-03-22-26-36-149.csv')
%data = readtable('/Users/mshafer/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA/2025-01-03-Egr_Lawn_Mower_Scan_with_Hanging_Monopole/Pulse-2025-01-03-22-26-36-149_THREE_PULSESE_WITH_HIGH_NOISE_CORRECTED.csv')
% data = readtable('/Users/mws22/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA/2025-01-13-Raymond Park Scan Flights/Pulse-2025-01-13-15-42-29-798.csv');
% readpulsetable handles every TagTracker header variant, needs no manual
% editing of the leading '#', and drops the 4-field rotation records that
% readtable would otherwise turn into pulses with a latitude in tag_id.
data = readpulsetable('/Users/mws22/Library/CloudStorage/OneDrive-NorthernArizonaUniversity/FLIGHT_TESTING_DATA/2025-01-13-Raymond Park Scan Flights/Pulse-2025-01-13-15-56-01-556.csv');



idMask = data.tag_id == 6;
data = data(idMask,:);

PROP = data.snr;
% PROP = data.stft_score;
%PROP = data.noise_psd;
lat = data.lat;
lon = data.lon;
alt = data.alt_rel;

home = [lat(1), lon(1), alt(end)];


[xEast, yNorth, zUp] = geo2enu(lat,lon,alt,home);
% [tagEast, tagNorth, tagAlt] = geo2enu(35.092097, -111.687142, 0, home); %KACHINA FLIGHT
tagLat = 35.094412;
tagLon = -111.687490;
[tagEast, tagNorth, tagAlt] = geo2enu(tagLat, tagLon, 0, home); %EGR QUAD FLIGHT

figure;

plot(xEast, yNorth, '.')
axis equal

% S = alphaShape(xEast,yNorth);
% S.Alpha = .3;
% plot(S)
% trisurf(S.alphaTriangulation,xEast,yNorth,alt)
% 
% tricontour(S.alphaTriangulation,xEast,yNorth,alt,10)
% hold on
% plot(xEast,yNorth,'ro')
% colorbar

colors = jet(100);
colorVals = linspace(min(PROP),max(PROP),100);
pointColors = interp1(colorVals,colors,PROP);
 

figure
scatter(xEast, yNorth,100, pointColors); hold on
scatter(tagEast, tagNorth,200,'b','filled','Marker','square');%,'Filled', 'square', 'Color')
xlabel('X-position (m)');ylabel('Y-position (m)');
grid on
axis equal


time = data.start_time_seconds-data.start_time_seconds(1);

figure;
plot(time, zUp); hold on
plot(time, xEast); hold on

%Descenct Plot
descentMask = time >= 0 & time <= 62;
colorValsDescent = linspace(min(PROP(descentMask)),max(PROP(descentMask)),100);
pointColorsMower = interp1(colorValsDescent,colors,PROP(descentMask));
figure;
plot(zUp(descentMask), PROP(descentMask)); hold on;
plot(zUp(descentMask), movmean(PROP(descentMask),8),'LineWidth',3)


%Mower Plot
mowerMask = time > 62 & time < 484;
colorValsMower = linspace(min(PROP(mowerMask)),max(PROP(mowerMask)),100);
pointColorsMower = interp1(colorValsMower,colors,PROP(mowerMask));
figure
scatter(xEast(mowerMask), yNorth(mowerMask),100, pointColorsMower); hold on
scatter(tagEast, tagNorth,200,'b','filled','Marker','square');%,'Filled', 'square', 'Color')
xlabel('X-position (m)');ylabel('Y-position (m)');
grid on
axis equal

PROPMower  = PROP(mowerMask);
mowerData = data(mowerMask,:);
xMower    = xEast(mowerMask);
yMower    = yNorth(mowerMask);

% bearingFromScatterPulse(lat(circleMask), lon(circleMask), alt(circleMask), PROP(circleMask), lat(1), lon(1), alt(1), 2)

k = convhull(xMower,yMower);
plot(xMower(k),yMower(k))
xMax = max(xMower);
yMax = max(yMower);
xMin = min(xMower);
yMin = min(yMower);
gridRes = 2;
yVec = floor(yMin):gridRes:ceil(yMax);
xVec = floor(xMin):gridRes:ceil(xMax);

mowerFig = figure;

[X,Y] = meshgrid(xVec, yVec);
[in, on] = inpolygon(X,Y,xMower(k),yMower(k));
[~,~,PROPGrid] = griddata(xMower,yMower,PROPMower,X,Y);
contourf(X,Y,PROPGrid,'FaceAlpha',0.2,'DisplayName','Interpolated PROP Map');
hColorbar = colorbar;
hColorbar.Label.String = 'Signal to Noise Ratio (dB)'
colormap jet
hold on
[FX,FY] = gradient(PROPGrid,gridRes);
% measuredBearing = atan2(mean(FY(:), 'omitnan'),mean(FX(:), 'omitnan'))*180/pi;
% normalizedYGrad = mean(FY(:), 'omitnan')/(sqrt(mean(FX(:), 'omitnan')^2 + mean(FY(:), 'omitnan')^2));
% normalizedXGrad = mean(FX(:), 'omitnan')/(sqrt(mean(FX(:), 'omitnan')^2 + mean(FY(:), 'omitnan')^2));
% quiver(mean(xCircle),mean(yCircle), 50*normalizedXGrad, 50*normalizedYGrad,'--','Color',[0.6 0.6 0.6],'Linewidth',1.5,'DisplayName','Calculated Bearing')

s = scatter(xEast(mowerMask), yNorth(mowerMask),100,pointColorsMower,"filled", 'DisplayName','Measured Pulses'); hold on
s.MarkerFaceAlpha = 0.4;
s.MarkerEdgeColor = 0.4*[1 1 1];
scatter(tagEast, tagNorth,200,'b','filled','Marker','diamond','DisplayName','Tag Location');%,'Filled', 'square', 'Color')
xlabel('X-position (m)');ylabel('Y-position (m)');
grid on
axis equal









[LAT, LON, zUp] = enu2geo(X,Y,zeros(size(X)),home);
%% write the KMZ
% Was the kmltoolbox (kml/createFolder/contourf/scatter/run). kmzwrite is a
% local function with no toolbox dependencies: it writes the surface as a
% GroundOverlay raster, puts the contour lines in their own switchable
% folder, and packages the marker icon inside the kmz so it renders offline.
kmzFile = fullfile(tempdir, 'MONOPOLE_SCAN_MAPPING.kmz');
kmzwrite(kmzFile, ...
    'Name',        'Monopole scan', ...
    'GridLat',     LAT, ...
    'GridLon',     LON, ...
    'GridValue',   PROPGrid, ...
    'ValueName',   'SNR (dB)', ...
    'MarkerLat',   tagLat, ...
    'MarkerLon',   tagLon, ...
    'MarkerName',  'Tag');
fprintf('Wrote %s\n', kmzFile);
system(sprintf('open "%s"', kmzFile));   % replaces f.run; comment out to skip



% quiver(X,Y,FX,FY,'k','Linewidth',1,'DisplayName','Gradient');axis equal; hold on

% figure
% streamline(X,Y,FX,FY,X(in),Y(in))
% figure
% scatter(X,Y)
% hold on;
% scatter(xMower(k),yMower(k),'kx')



%Range Plot
rangeMask = time<670 & time>404;
colorValsRange = linspace(min(PROP(rangeMask)),max(PROP(rangeMask)),100);
pointColorsRange = interp1(colorValsRange,colors,PROP(rangeMask));
figure
scatter(xEast(rangeMask), yNorth(rangeMask),100, pointColorsRange); hold on
scatter(tagEast, tagNorth,200,'b','filled','Marker','square');%,'Filled', 'square', 'Color')
xlabel('X-position (m)');ylabel('Y-position (m)');
grid on
axis equal

rangeToTag = sqrt((xEast-tagEast).^2 + (yNorth-tagNorth).^2);

figure;
plot(rangeToTag(rangeMask), PROP(rangeMask));%,'Filled', 'square', 'Color')
xlabel('Range (m)')
ylabel('PROP (dB)')
grid on





%Circle Plot
circleMask = time<367 & time>300;

colorValsCircle = linspace(min(PROP(circleMask)),max(PROP(circleMask)),100);
pointColorsCircle = interp1(colorValsCircle,colors,PROP(circleMask));

PROPCircle = PROP(circleMask);
circleData = data(circleMask,:);
xCircle = xEast(circleMask);
yCircle = yNorth(circleMask);

% bearingFromScatterPulse(lat(circleMask), lon(circleMask), alt(circleMask), PROP(circleMask), lat(1), lon(1), alt(1), 2)

k = convhull(xCircle,yCircle);
plot(xCircle(k),yCircle(k))
xMax = max(xCircle);
yMax = max(yCircle);
xMin = min(xCircle);
yMin = min(yCircle);
gridRes = 2;
yVec = floor(yMin):gridRes:ceil(yMax);
xVec = floor(xMin):gridRes:ceil(xMax);

bearingFig = figure;

[X,Y] = meshgrid(xVec, yVec);
[in, on] = inpolygon(X,Y,xCircle(k),yCircle(k));
[~,~,PROPGrid] = griddata(xCircle,yCircle,PROPCircle,X,Y);
contourf(X,Y,PROPGrid,'FaceAlpha',0.2,'DisplayName','Interpolated PROP Map');
hColorbar = colorbar;
hColorbar.Label.String = 'Signal to Noise Ratio (dB)'
colormap jet
hold on
[FX,FY] = gradient(PROPGrid,gridRes);
measuredBearing = atan2(mean(FY(:), 'omitnan'),mean(FX(:), 'omitnan'))*180/pi;
normalizedYGrad = mean(FY(:), 'omitnan')/(sqrt(mean(FX(:), 'omitnan')^2 + mean(FY(:), 'omitnan')^2));
normalizedXGrad = mean(FX(:), 'omitnan')/(sqrt(mean(FX(:), 'omitnan')^2 + mean(FY(:), 'omitnan')^2));
quiver(mean(xCircle),mean(yCircle), 50*normalizedXGrad, 50*normalizedYGrad,'--','Color',[0.6 0.6 0.6],'Linewidth',1.5,'DisplayName','Calculated Bearing')

s = scatter(xEast(circleMask), yNorth(circleMask),100,pointColorsCircle,"filled", 'DisplayName','Measured Pulses'); hold on
s.MarkerFaceAlpha = 0.4
s.MarkerEdgeColor = 0.4*[1 1 1];
scatter(tagEast, tagNorth,200,'b','filled','Marker','diamond','DisplayName','Tag Location');%,'Filled', 'square', 'Color')
xlabel('X-position (m)');ylabel('Y-position (m)');
grid on
axis equal


quiver(X,Y,FX,FY,'k','Linewidth',1,'DisplayName','Gradient');axis equal; hold on

trueDY = tagNorth-mean(yCircle);
trueDX = tagEast-mean(xCircle);
bearingX = trueDX/sqrt(trueDX^2+trueDY^2);
bearingY = trueDY/sqrt(trueDX^2+trueDY^2);
quiver(mean(xCircle),mean(yCircle), 50*bearingX, 50*bearingY,'-','Color',[0.6 0.6 0.6],'Linewidth',1.5,'DisplayName','True Bearing')
trueBearing = 180/pi*atan2(trueDY, trueDX);

bearingError = abs(measuredBearing-trueBearing)

legend('location','southeast')
xlim([-50 20])
ylim([15 90])

% % set(gca,'TickLabelInterpreter','latex')
% saveString = 'MONOPOLE_BEARING'
% %FIGURE PREP FOR PAPER
% real_fig_width = 8; %Desired with in latex-
% real_fig_height = 9; %Desired with in latex-
% scale_factor = 3;   %Scaled figure up by this so it appears the large on screen in matlab
% real_fig_font_size = 6;
% real_fig_legend_font_size = 5;
% scaled_width = scale_factor*real_fig_width;
% scaled_height = scale_factor*real_fig_height;
% scaled_font_size = real_fig_font_size * scale_factor;
% scaled_legend_font_size = real_fig_legend_font_size * scale_factor;
% set(findall(gcf,'-property','FontSize'),'FontSize',scaled_font_size)%Change all the other font sizes
% set(findobj(gcf, 'Type', 'Legend'),'FontSize',scaled_legend_font_size)%Change the legend font sizes
% PUBFIGPREP(bearingFig,'width',scaled_width,'height',scaled_height,'margin','on')
% 
% % %Make room for the color bar
%  bearingFig.Position = bearingFig.Position + [0 0 3 0];
% % bearingFig.Position = bearingFig.Position + [0 0 0 -2];
% % bearingFig.Position = bearingFig.Position + [1 0 0 0];
% pos = get(bearingFig,'Position');
% set(bearingFig,'PaperPositionMode','Auto','PaperUnits','centimeters','PaperSize',[pos(3), pos(4)])
% 
% 
% 
% results_location = 'Processed_figures';
% %results_location = '';
% print([results_location,'/',saveString],'-dpdf','-fillpage')
% % saveas(voltageFig,[results_location ,'/',savestring,'-polar-example'],'pdf')
