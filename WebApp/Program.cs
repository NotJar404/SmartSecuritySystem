using Microsoft.AspNetCore.Authentication.Cookies;
using WebApp.Services;

var builder = WebApplication.CreateBuilder(args);

// =========================
// ADD SERVICES
// =========================

// Add MVC controllers + views
builder.Services.AddControllersWithViews();

// Add session support
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromMinutes(30);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
});

// Add authentication (cookies)
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.LoginPath = "/Auth/Login";          // Redirect if not logged in
        options.AccessDeniedPath = "/Auth/Login";   // Redirect if role denied
    });

// Add authorization
builder.Services.AddAuthorization();

// Add your services
builder.Services.AddSingleton<AuthService>();  // 🔹 In-memory AuthService
builder.Services.AddScoped<SystemService>();   // Your other service

// =========================
// BUILD APP
// =========================
var app = builder.Build();

// =========================
// MIDDLEWARE
// =========================
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseStaticFiles();

app.UseRouting();

app.UseSession();          // must be BEFORE auth
app.UseAuthentication();   // must be BEFORE authorization
app.UseAuthorization();

// =========================
// ROUTES
// =========================
app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Auth}/{action=Login}/{id?}");

// =========================
// RUN
// =========================
app.Run();