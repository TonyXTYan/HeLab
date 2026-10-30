function run_matlab_cases(variant, cases_dir, work_dir)
% Run one MATLAB converter variant on copies of every case (crosscheck, Lens).
% variant: '2019' (tdc_autoconverter, dld_raw_to_txy_counts) or '2023' (DLD_front_panel,
% dld_raw_to_txy). Copies <cases_dir>/<case>/d1.txt to <work_dir>/<variant>/<case>/d1.txt,
% converts there, copies the output back as expected-<variant>.txt and records the outcome in
% <cases_dir>/<case>/matlab-<variant>.json. Never writes into legacy/ or the cases' d1.txt.
root = fileparts(fileparts(fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))))));
if strcmp(variant, '2019')
    addpath(fullfile(root, 'legacy', 'tdc_autoconverter', 'lib'));
    conv = @(base) dld_raw_to_txy_counts(base, 1, 1);
else
    addpath(fullfile(root, 'legacy', 'DLD_front_panel', 'lib', 'Core_BEC_Analysis', 'lib', 'import_mcp_tdc_data'));
    conv = @(base) dld_raw_to_txy(base, 1, 1);
end
fprintf('using %s\n', which('dld_read_5channels_reconst_multi_imp'));
d = dir(cases_dir);
for k = 1:numel(d)
    if ~d(k).isdir || d(k).name(1) == '.'; continue; end
    name = d(k).name;
    src = fullfile(cases_dir, name, 'd1.txt');
    if ~isfile(src); continue; end
    wd = fullfile(work_dir, variant, name);
    if isfolder(wd); rmdir(wd, 's'); end
    mkdir(wd);
    copyfile(src, fullfile(wd, 'd1.txt'));
    exp_file = fullfile(cases_dir, name, ['expected-' variant '.txt']);
    if isfile(exp_file); delete(exp_file); end
    res = struct('variant', variant, 'matlab', version, 'status', '', 'message', '', 'hits', 0);
    try
        conv(fullfile(wd, 'd'));
        out = fullfile(wd, 'd_txy_forc1.txt');
        if isfile(out)
            copyfile(out, exp_file);
            res.status = 'file';
            txt = fileread(out);
            res.hits = sum(txt == newline);
        else
            res.status = 'nofile';
        end
    catch e
        res.status = 'error';
        res.message = [e.identifier ': ' e.message];
    end
    fid = fopen(fullfile(cases_dir, name, ['matlab-' variant '.json']), 'w');
    fprintf(fid, '%s\n', jsonencode(res, 'PrettyPrint', true));
    fclose(fid);
    fprintf('%-22s %-7s %5d %s\n', name, res.status, res.hits, res.message);
end
end
