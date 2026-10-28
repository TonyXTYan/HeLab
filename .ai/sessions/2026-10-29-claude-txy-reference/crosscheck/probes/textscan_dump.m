names = strsplit(fileread('fuzzts/list.txt'), newline);
out = fopen('fuzzts/matlab.txt', 'w');
for i=1:numel(names)
  fid=fopen(['fuzzts/' names{i} '.txt']);
  d = textscan(fid,'%f64%f64','Delimiter', ',','MultipleDelimsAsOne',0,'ReturnOnError', true,'NumCharactersToSkip',0,'CollectOutput', true);
  fclose(fid); d = d{1};
  fprintf(out, '%s %d', names{i}, size(d,1)); fprintf(out, ' %.17g', d'); fprintf(out, '\n');
end
fclose(out);
