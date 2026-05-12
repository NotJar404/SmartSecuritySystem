using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.EntityFrameworkCore;
using SmartSecuritySystem.Filters;
using WebApp.Data;

var builder = WebApplication.CreateBuilder(args);

// =========================
// SERVICES 
// =========================

// MVC + Global Filters
builder.Services.AddControllersWithViews(options =>
{
    // Force new accounts to change password before accessing any page
    options.Filters.Add<ForcePasswordChangeFilter>();
});

// =========================
// DATABASE (POSTGRESQL)
// =========================
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(
        builder.Configuration.GetConnectionString("DefaultConnection")
    )
);

// =========================
// SESSION (OPTIONAL)
// =========================
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromMinutes(30);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
});

// =========================
// AUTHENTICATION (COOKIE)
// =========================
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.LoginPath = "/Auth/Login";
        options.AccessDeniedPath = "/Auth/Login";

        // 🔥 IMPORTANT FIXES
        options.Cookie.Name = "SmartSecurityAuth";
        options.Cookie.HttpOnly = true;
        options.ExpireTimeSpan = TimeSpan.FromMinutes(60);
        options.SlidingExpiration = true;

        // Prevent weird redirect loops
        options.ReturnUrlParameter = "returnUrl";

        // Helps avoid cookie issues
        options.Cookie.SameSite = SameSiteMode.Lax;
    });

// Authorization
builder.Services.AddAuthorization();

// =========================
// BUILD APP
// =========================
var app = builder.Build();

// =========================
// CONFIGURE URLS / PORTS
// =========================
var httpPort = Environment.GetEnvironmentVariable("ASPNETCORE_HTTP_PORT") ?? "5145";
// Clear default URLs and bind to both localhost AND all interfaces
app.Urls.Clear();
app.Urls.Add($"http://127.0.0.1:{httpPort}");      // For localhost connections
app.Urls.Add($"http://0.0.0.0:{httpPort}");        // For network connections
Console.WriteLine($"\n🚀 ASP.NET Server listening on:");
Console.WriteLine($"   - http://localhost:{httpPort} (local)");
Console.WriteLine($"   - http://127.0.0.1:{httpPort} (localhost)");
Console.WriteLine($"   - http://0.0.0.0:{httpPort} (all interfaces)\n");

// =========================
// MIDDLEWARE
// =========================
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
    app.UseHsts();
}

//app.UseHttpsRedirection();
app.UseStaticFiles();

app.UseRouting();

// 🔥 ORDER IS CRITICAL (YOURS WAS GOOD)
app.UseSession();          // optional
app.UseAuthentication();   // MUST come before Authorization
app.UseAuthorization();

// =========================
// ROUTES
// =========================
app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Auth}/{action=Login}/{id?}"
);

app.Run();