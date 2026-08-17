using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace UAInstaller;

public partial class MainWindow : Window
{
    private string? _gameDir;
    private static readonly string DataDir = ExtractPayload();
    private static string Hpatchz => Path.Combine(DataDir, "hpatchz.exe");

    /// Вшиті в exe диффи розпаковуються в тимчасову папку при старті.
    private static string ExtractPayload()
    {
        var dir = Path.Combine(Path.GetTempPath(), "nrftw-ua-text");
        Directory.CreateDirectory(dir);
        var asm = System.Reflection.Assembly.GetExecutingAssembly();
        foreach (var res in asm.GetManifestResourceNames())
        {
            const string prefix = "UAInstaller.payload.";
            if (!res.StartsWith(prefix)) continue;
            var name = res.Substring(prefix.Length);
            var dest = Path.Combine(dir, name);
            using var s = asm.GetManifestResourceStream(res)!;
            if (File.Exists(dest) && new FileInfo(dest).Length == s.Length) continue;
            using var f = File.Create(dest);
            s.CopyTo(f);
        }
        return dir;
    }

    private static readonly Brush Fg = new SolidColorBrush(Color.FromRgb(0xD8, 0xD8, 0xD8));
    private static readonly Brush Dim = new SolidColorBrush(Color.FromRgb(0x5C, 0x61, 0x66));
    private static readonly Brush Ok = new SolidColorBrush(Color.FromRgb(0x6F, 0xBF, 0x73));
    private static readonly Brush Err = new SolidColorBrush(Color.FromRgb(0xCF, 0x6A, 0x5A));

    /// Пошук гри як робить сам Steam: реєстр → libraryfolders.vdf → усі бібліотеки.
    private static IEnumerable<string> CandidateGameDirs()
    {
        var steamRoots = new List<string>();
        foreach (var regPath in new[] { @"HKEY_CURRENT_USER\Software\Valve\Steam",
                                        @"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam" })
        {
            try
            {
                var v = Microsoft.Win32.Registry.GetValue(regPath, "SteamPath", null)
                     ?? Microsoft.Win32.Registry.GetValue(regPath, "InstallPath", null);
                if (v is string s && Directory.Exists(s)) steamRoots.Add(s.Replace('/', '\\'));
            }
            catch { }
        }
        steamRoots.Add(@"C:\Program Files (x86)\Steam");

        var libs = new List<string>(steamRoots);
        foreach (var root in steamRoots.Distinct())
        {
            var vdf = Path.Combine(root, "steamapps", "libraryfolders.vdf");
            if (!File.Exists(vdf)) continue;
            foreach (var line in File.ReadLines(vdf))
            {
                // рядки виду:  "path"  "D:\\SteamLibrary"
                var m = System.Text.RegularExpressions.Regex.Match(line, "\"path\"\\s+\"(.+?)\"");
                if (m.Success) libs.Add(m.Groups[1].Value.Replace(@"\\", @"\"));
            }
        }
        foreach (var lib in libs.Distinct())
            yield return Path.Combine(lib, "steamapps", "common", "NoRestForTheWicked");
        // фолбек: типові шляхи на всіх дисках
        foreach (var d in DriveInfo.GetDrives().Where(d => d.DriveType == DriveType.Fixed))
            yield return Path.Combine(d.Name, "SteamLibrary", "steamapps", "common", "NoRestForTheWicked");
    }

    public MainWindow()
    {
        InitializeComponent();
        Loaded += (_, _) => DetectGame();
    }

    private void Drag(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState == MouseButtonState.Pressed) DragMove();
    }

    private void CloseClick(object sender, RoutedEventArgs e) => Close();
    private void MinClick(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    // ---------- консоль ----------

    private TextBlock Log(string text, Brush? fg = null)
    {
        var tb = new TextBlock
        {
            Text = text,
            FontSize = 12.5,
            Foreground = fg ?? Dim,
            TextTrimming = TextTrimming.CharacterEllipsis,
            Margin = new Thickness(0, 1.5, 0, 1.5),
        };
        Term.Children.Add(tb);
        Scroller.ScrollToEnd();
        return tb;
    }

    private void SetStatus(string s) => StatusText.Text = s;

    private void SetPercent(double frac, bool show = true)
    {
        PercentText.Text = show ? $"{frac * 100:0.0}%" : "";
        var track = (FrameworkElement)ProgressFill.Parent;
        ProgressFill.Width = Math.Max(0, track.ActualWidth * Math.Min(1, frac));
    }

    // ---------- виявлення гри ----------

    private void DetectGame()
    {
        _gameDir = CandidateGameDirs().FirstOrDefault(p => File.Exists(Path.Combine(p, "NoRestForTheWicked.exe")));
        RefreshGameState();
    }

    private void BrowseClick(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Вкажи NoRestForTheWicked.exe",
            Filter = "Гра|NoRestForTheWicked.exe"
        };
        if (dlg.ShowDialog() == true)
        {
            _gameDir = Path.GetDirectoryName(dlg.FileName);
            RefreshGameState();
        }
    }

    /// Розміри ОРИГІНАЛЬНИХ файлів гри (payload/sizes.txt: "відносний шлях|байти").
    /// Потрібні, щоб відрізнити чисту гру від уже пропатченої: hpatchz працює
    /// лише з оригінальними байтами, тож патч поверх патча гарантовано впаде.
    private static readonly Dictionary<string, long> OriginalSizes = LoadSizes();

    private static Dictionary<string, long> LoadSizes()
    {
        var d = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var p = Path.Combine(DataDir, "sizes.txt");
        if (!File.Exists(p)) return d;
        foreach (var line in File.ReadAllLines(p))
        {
            var i = line.LastIndexOf('|');
            if (i > 0 && long.TryParse(line.Substring(i + 1), out var n))
                d[line.Substring(0, i).Replace('/', '\\')] = n;
        }
        return d;
    }

    private (List<(string rel, string diff)> jobs, List<string> missing, List<string> stale) ScanJobs()
    {
        var jobs = new List<(string, string)>();
        var missing = new List<string>();
        var stale = new List<string>();
        if (_gameDir == null) return (jobs, missing, stale);
        foreach (var diff in Directory.EnumerateFiles(DataDir, "*.hdiff").OrderBy(f => new FileInfo(f).Length))
        {
            var rel = Path.GetFileNameWithoutExtension(diff).Replace('~', Path.DirectorySeparatorChar);
            var target = Path.Combine(_gameDir, rel);
            if (!File.Exists(target)) { missing.Add(Path.GetFileName(rel)); continue; }
            if (OriginalSizes.TryGetValue(rel, out var want) && new FileInfo(target).Length != want)
                stale.Add(Path.GetFileName(rel));
            jobs.Add((rel, diff));
        }
        return (jobs, missing, stale);
    }

    private void RefreshGameState()
    {
        Term.Children.Clear();
        // hpatchz працює лише з оригінальними байтами, тому це перше, що видно
        Log("ставиться ЛИШЕ на оригінальні файли гри", Fg);
        Log("без інших модів і без попередніх версій українізатора");
        Log("");
        if (_gameDir == null)
        {
            SetStatus("гру не знайдено");
            Log("вкажи папку гри вручну — кнопка внизу", Err);
            InstallBtn.IsEnabled = false;
            return;
        }
        Log("гра        " + _gameDir);
        var (jobs, missing, stale) = ScanJobs();
        if (missing.Count > 0)
        {
            SetStatus("версія гри не збігається");
            Log("файли гри не збігаються з цим патчем — гра оновилась", Err);
            Log("чекай оновлення NRFTW-UA-TEXT · нічого не змінено");
            InstallBtn.IsEnabled = false;
        }
        else if (stale.Count > 0)
        {
            SetStatus("потрібні оригінальні файли");
            Log("гру вже пропатчено попередньою версією українізатора", Err);
            Log("патч накладається лише на оригінальні файли гри");
            Log("");
            Log("натисни «відкат» · Steam перевірить цілісність і поверне оригінали", Fg);
            Log("коли Steam завершить — запусти цей інсталятор ще раз");
            InstallBtn.IsEnabled = false;
        }
        else
        {
            long total = jobs.Sum(j => new FileInfo(Path.Combine(_gameDir!, j.rel)).Length);
            SetStatus("готовий до встановлення");
            Log($"версія     ok");
            Log($"файлів     {jobs.Count} · {total / 1e9:0.0} GB");
            InstallBtn.IsEnabled = jobs.Count > 0;
        }
    }

    // ---------- встановлення ----------

    private async void InstallClick(object sender, RoutedEventArgs e)
    {
        if (_gameDir == null) return;
        if (Process.GetProcessesByName("NoRestForTheWicked").Length > 0)
        {
            Log("закрий гру — її файли зайняті", Err);
            return;
        }
        var (jobs, _, _) = ScanJobs();
        long totalBytes = jobs.Sum(j => new FileInfo(Path.Combine(_gameDir, j.rel)).Length);
        long doneBytes = 0;
        InstallBtn.IsEnabled = false;
        RollbackBtn.IsEnabled = false;
        BrowseBtn.IsEnabled = false;
        SetStatus("встановлення");

        try
        {
            for (int i = 0; i < jobs.Count; i++)
            {
                var (rel, diff) = jobs[i];
                var target = Path.Combine(_gameDir, rel);
                var name = Path.GetFileName(rel);
                long size = new FileInfo(target).Length;
                var line = Log($"{name}", Fg);
                var tmp = target + ".ua_tmp";

                // плавний прогрес: hpatchz пише вихідний файл — стежимо за його розміром
                long captured = doneBytes;
                var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(80) };
                timer.Tick += (_, _) =>
                {
                    long cur = 0;
                    try { cur = new FileInfo(tmp).Length; } catch { }
                    cur = Math.Min(cur, size);
                    line.Text = $"{name}   {cur / 1e6:0} / {size / 1e6:0} MB";
                    SetPercent((captured + cur) / (double)totalBytes);
                };
                timer.Start();

                var okRun = await Task.Run(() => RunHpatch(target, diff, tmp));
                timer.Stop();
                if (!okRun)
                {
                    try { File.Delete(tmp); } catch { }
                    line.Text = $"{name}   помилка";
                    line.Foreground = Err;
                    SetStatus("помилка — нічого не зіпсовано");
                    Log("оригінальний файл не чіпався", Err);
                    Log("найімовірніше цей файл уже змінено — натисни «відкат»,");
                    Log("дочекайся перевірки Steam і запусти інсталятор ще раз");
                    ResetButtons();
                    return;
                }
                File.Move(tmp, target, overwrite: true);
                doneBytes += size;
                line.Text = $"{name}   ok";
                line.Foreground = Ok;
                SetPercent(doneBytes / (double)totalBytes);
            }

            SetPercent(1);
            SetStatus("готово");
            Log("");
            Log("Settings → Language → «Українська»", Fg);
        }
        catch (Exception ex)
        {
            SetStatus("помилка");
            Log(ex.Message, Err);
        }
        ResetButtons();
    }

    private void ResetButtons()
    {
        InstallBtn.IsEnabled = true;
        RollbackBtn.IsEnabled = true;
        BrowseBtn.IsEnabled = true;
    }

    private static bool RunHpatch(string oldFile, string diff, string outFile)
    {
        var psi = new ProcessStartInfo
        {
            FileName = Hpatchz,
            Arguments = $"-f \"{oldFile}\" \"{diff}\" \"{outFile}\"",
            CreateNoWindow = true,
            UseShellExecute = false,
        };
        using var p = Process.Start(psi)!;
        p.WaitForExit();
        return p.ExitCode == 0 && File.Exists(outFile);
    }

    private void RollbackClick(object sender, RoutedEventArgs e)
    {
        Process.Start(new ProcessStartInfo("steam://validate/1371980") { UseShellExecute = true });
        Log("перевірка цілісності Steam поверне оригінальні файли", Fg);
    }
}
