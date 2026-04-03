using Microsoft.AspNetCore.Authentication.Cookies;
using WebApp.Services;

var builder = WebApplication.CreateBuilder(args);

// =========================
// ADD SERVICES
// =========================

// Add MVC
builder.Services.AddControllersWithViews();

// Session
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromMinutes(30);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
});

// Authentication (Cookies)
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.LoginPath = "/Auth/Login";
        options.AccessDeniedPath = "/Auth/Login";
    });

// Authorization
builder.Services.AddAuthorization();

// =========================
// 🔥 IMPORTANT: SERVICES
// =========================

// Auth (in-memory is fine)
builder.Services.AddSingleton<AuthService>();

// ✅ FIXED: MUST BE SINGLETON (NOT SCOPED)
// 🔹 FOR DATABASE INTEGRATION:
//    - Change to AddScoped<SystemService>() when using DbContext
//    - Add DbContext: builder.Services.AddDbContext<SecurityDbContext>()
//    - Inject repositories: AddScoped(typeof(IRepository<>), typeof(GenericRepository<>))
//    - Replace in-memory data with database queries
builder.Services.AddSingleton<SystemService>();

// 🔹 TODO: Add these when database is ready:
// builder.Services.AddDbContext<SecurityDbContext>(options =>
//     options.UseSqlServer(builder.Configuration.GetConnectionString("DefaultConnection")));
// builder.Services.AddScoped(typeof(IRepository<>), typeof(GenericRepository<>));
// builder.Services.AddScoped<ISystemRepository, SystemRepository>();

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

// 🔥 ORDER IS IMPORTANT
app.UseSession();
app.UseAuthentication();
app.UseAuthorization();

// =========================
// ROUTING
// =========================

app.MapControllerRoute(
    name: "default",
    pattern: "{controller=System}/{action=Index}/{id?}"
);

// =========================
// RUN
// =========================

app.Run();